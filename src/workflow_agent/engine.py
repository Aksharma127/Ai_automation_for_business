"""The agent: a LangGraph state machine that runs any workflow in the registry.

    understand_request ──► (no match) ──► clarify ──► END
            │
            ▼
      extract_inputs
            │
            ▼
    ┌─► execute_step ── next step? ──┐
    └────────────────────────────────┘
            │ done / halted / failed
            ▼
        finalize ──► END

Nothing in this file knows about a specific workflow: steps, tools, arguments, decision
rules and report layout all come from the registry (Excel + YAML bindings).
"""
from __future__ import annotations

import csv
import operator
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import llm as llm_api
from .extractor import extract_inputs
from .registry import Registry, StepBinding, load_registry
from .router import make_router
from .settings import ROOT, Settings, get_settings
from .tools import ToolContext, call_tool
from .tools.base import ToolError, TransientToolError, WorkflowHalt
from .tools.content import render_template


class AgentState(TypedDict, total=False):
    request: str
    run_id: str
    route: dict[str, Any]
    workflow_id: str | None
    workflow_name: str | None
    inputs: dict[str, Any]
    memory: dict[str, Any]  # step outputs by save_as name
    step_index: int
    trace: Annotated[list[dict[str, Any]], operator.add]
    status: str  # running | completed | needs_input | escalated | failed | no_workflow
    message: str | None
    result: dict[str, Any] | None
    answer: str | None
    notes: list[str]


# ---------------------------------------------------------------------------------------------
# "$ref" resolution: binding arguments refer to request inputs and earlier step outputs
# ---------------------------------------------------------------------------------------------

def resolve(value: Any, scope: dict[str, Any]) -> Any:
    """Resolve "$a.b|filter" strings (recursively inside lists/dicts) against the scope."""
    if isinstance(value, str) and value.startswith("$"):
        path, _, flt = value[1:].partition("|")
        cur: Any = scope
        for part in path.split("."):
            if isinstance(cur, dict):
                if part not in cur:
                    raise ToolError(f"reference {value!r}: '{part}' not found")
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            else:
                raise ToolError(f"reference {value!r}: cannot read '{part}' from {type(cur).__name__}")
        return _filter(cur, flt) if flt else cur
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def _filter(v: Any, flt: str) -> Any:
    name, _, arg = flt.partition(":")
    if name == "count":
        return len(v or [])
    if name == "first":
        return v[0] if v else None
    if name == "join":
        return (arg or ", ").join(str(x) for x in (v or []))
    if name == "sum":
        total = round(sum(float(x.get(arg) or 0) for x in (v or [])), 2)
        return int(total) if total.is_integer() else total
    if name == "count_eq":
        field_name, _, want = arg.partition("=")
        return sum(1 for x in (v or []) if str(x.get(field_name)) == want)
    if name == "count_ne":
        field_name, _, want = arg.partition("=")
        return sum(1 for x in (v or []) if str(x.get(field_name)) != want)
    if name == "pluck":
        return [x.get(arg) for x in (v or [])]
    raise ToolError(f"unknown filter |{name}")


def summarize_output(out: Any) -> str:
    if isinstance(out, list):
        return f"{len(out)} record(s)"
    if isinstance(out, dict):
        parts = [f"{k}: {len(v)}" if isinstance(v, (list, dict)) else f"{k}: {v}" for k, v in list(out.items())[:4]]
        return ", ".join(parts)
    s = str(out)
    return s if len(s) <= 90 else s[:87] + "..."


# ---------------------------------------------------------------------------------------------

class WorkflowAgent:
    def __init__(self, settings: Settings | None = None, llm: Any = "auto", registry: Registry | None = None):
        self.settings = settings or get_settings()
        self.llm = llm_api.get_llm(self.settings) if llm == "auto" else llm
        self.registry = registry or load_registry(self.settings.workflow_excel, self.settings.bindings_file)
        self.router = make_router(self.registry.executable(), self.llm)
        self.graph = self._build_graph()

    # -- graph -----------------------------------------------------------------------------
    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("understand_request", self._understand)
        g.add_node("clarify", self._clarify)
        g.add_node("extract_inputs", self._extract)
        g.add_node("execute_step", self._execute_step)
        g.add_node("finalize", self._finalize)
        g.add_edge(START, "understand_request")
        g.add_conditional_edges("understand_request", lambda s: "extract_inputs" if s.get("workflow_id") else "clarify")
        g.add_edge("clarify", END)
        g.add_edge("extract_inputs", "execute_step")
        g.add_conditional_edges("execute_step", self._next)
        g.add_edge("finalize", END)
        return g.compile()

    def _next(self, s: AgentState) -> str:
        wf = self.registry.get(s["workflow_id"])
        if s["status"] == "running" and s["step_index"] < len(wf.steps):
            return "execute_step"
        return "finalize"

    # -- nodes -----------------------------------------------------------------------------
    def _understand(self, s: AgentState) -> AgentState:
        d = self.router.route(s["request"], self.settings.min_route_confidence)
        route = {"workflow_id": d.workflow_id, "confidence": d.confidence, "reasoning": d.reasoning,
                 "method": d.method, "candidates": d.candidates}
        if not d.workflow_id:
            return {"route": route, "workflow_id": None, "status": "no_workflow"}
        wf = self.registry.get(d.workflow_id)
        return {"route": route, "workflow_id": wf.id, "workflow_name": wf.name, "status": "running",
                "step_index": 0, "memory": {}, "notes": []}

    def _clarify(self, s: AgentState) -> AgentState:
        options = "\n".join(f"  - {w.name}: {w.trigger}" for w in self.registry.executable())
        guess = s["route"]["candidates"][:2]
        hint = (" Did you mean " + " or ".join(c["name"] for c in guess) + "?") if guess and guess[0]["score"] > 0 else ""
        msg = f"I couldn't confidently match your request to a workflow.{hint}\nI can help with:\n{options}"
        return {"message": msg, "answer": msg}

    def _extract(self, s: AgentState, config) -> AgentState:
        ctx: ToolContext = config["configurable"]["ctx"]
        wf = self.registry.get(s["workflow_id"])
        inputs = extract_inputs(wf, s["request"], self.llm, ctx.notes)
        inputs["request"] = s["request"]
        return {"inputs": inputs}

    def _execute_step(self, s: AgentState, config) -> AgentState:
        ctx: ToolContext = config["configurable"]["ctx"]
        wf = self.registry.get(s["workflow_id"])
        i = s["step_index"]
        step = wf.steps[i]
        memory = dict(s["memory"])
        scope = {"inputs": s["inputs"], **memory}
        rec: dict[str, Any] = {"n": i + 1, "step": step.label, "tool": step.tool, "attempts": 0}
        t0 = time.perf_counter()
        status, message = "running", None
        try:
            args = resolve(step.args, scope)
            out = self._call_with_policy(step, args, ctx, rec)
            memory[step.save_as] = out
            rec["status"] = rec.get("status", "ok")
            rec["output"] = self._describe(step, out, scope)
        except WorkflowHalt as h:
            rec.update(status=h.status, output=h.message)
            status, message = h.status, h.message
            memory["_halt"] = h.data
        except Exception as exc:  # unrecoverable: stop with a clear error, never a stack trace
            err = f"{type(exc).__name__}: {exc}"
            if step.on_error == "continue":
                memory[step.save_as] = None
                rec.update(status="error-continued", output=err)
                ctx.note(f"step {i + 1} '{step.label}' failed and was skipped: {exc}")
            else:
                rec.update(status="failed", output=err)
                status, message = "failed", f"Step {i + 1} '{step.label}' failed: {exc}"
        rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if status == "running" and i + 1 == len(wf.steps):
            status = "completed"
        return {"memory": memory, "step_index": i + 1, "trace": [rec], "status": status, "message": message}

    def _call_with_policy(self, step: StepBinding, args: dict[str, Any], ctx: ToolContext, rec: dict) -> Any:
        last: Exception | None = None
        for attempt in range(step.retries + 1):
            rec["attempts"] = attempt + 1
            try:
                return call_tool(step.tool, args, ctx)
            except TransientToolError as exc:
                last = exc
                rec.setdefault("retries", []).append(str(exc))
                time.sleep(min(0.05 * 2 ** attempt, 0.5))  # exponential backoff (kept tiny for the demo)
        if step.on_error == "degrade" and step.fallback_tool:
            rec["status"] = "degraded"
            rec["tool"] = f"{step.tool} → {step.fallback_tool}"
            return call_tool(step.fallback_tool, args, ctx)
        raise ToolError(f"{last} (after {step.retries + 1} attempt(s))")

    def _describe(self, step: StepBinding, out: Any, scope: dict[str, Any]) -> str:
        if step.describe:
            try:
                values: dict[str, Any] = {"count": len(out) if isinstance(out, (list, dict)) else None}
                if isinstance(out, dict):
                    for k, v in out.items():
                        if isinstance(v, list):
                            scalar = all(not isinstance(x, (dict, list)) for x in v)
                            joined = ", ".join(map(str, v))
                            values[k] = joined if scalar and v and len(joined) <= 80 else len(v)
                        elif isinstance(v, dict):
                            values[k] = len(v)
                            values.update({f"{k}.{kk}": vv for kk, vv in v.items() if not isinstance(vv, (dict, list))})
                        else:
                            values[k] = v
                return render_template(step.describe, values) or summarize_output(out)
            except Exception:
                pass
        return summarize_output(out)

    def _finalize(self, s: AgentState, config) -> AgentState:
        ctx: ToolContext = config["configurable"]["ctx"]
        wf = self.registry.get(s["workflow_id"])
        if s["status"] != "completed":
            return {"result": None, "answer": s.get("message"), "notes": ctx.notes}
        try:
            report = build_report(wf.report, {"inputs": s["inputs"], **s["memory"]}, wf.name)
        except Exception as exc:
            ctx.note(f"report layout error: {exc}")
            report = {"title": wf.name, "summary": "Completed.", "sections": []}
        answer = report["summary"]
        if self.llm is not None and wf.report.get("narrate", True):
            try:
                answer = llm_api.ask_text(
                    self.llm, "Write a 1-3 sentence answer to the user's request using ONLY the result data. "
                              "No markdown headings.",
                    f"Request: {s['request']}\nResult: {llm_api.as_json(report)[:6000]}")
            except Exception as exc:
                ctx.note(f"LLM summary unavailable ({type(exc).__name__})")
        return {"result": report, "answer": answer, "notes": ctx.notes}

    # -- public API --------------------------------------------------------------------------
    def run(self, request: str) -> dict[str, Any]:
        run_id = f"RUN-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
        ctx = ToolContext(llm=self.llm, root=ROOT, output_dir=self.settings.output_dir, run_id=run_id)
        state = self.graph.invoke({"request": request, "run_id": run_id, "trace": []},
                                  config={"configurable": {"ctx": ctx}})
        state.setdefault("notes", ctx.notes)
        state["mode"] = llm_api.describe(self.llm)
        self._log_run(state)
        return state

    def _log_run(self, s: dict[str, Any]) -> None:
        """Append to the run log in the same format WF010 analyses, so the agent can report on itself."""
        if not s.get("workflow_id"):
            return
        path = self.settings.run_log
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with path.open("a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["run_id", "timestamp", "workflow_id", "workflow_name", "step", "status", "duration_sec",
                            "error_message"])
            for t in s.get("trace", []):
                ok = t["status"] in {"ok", "degraded", "needs_input", "escalated"}
                w.writerow([s["run_id"], ts, s["workflow_id"], s["workflow_name"], t["step"],
                            "success" if ok else "failed", round(t["ms"] / 1000, 3), "" if ok else t["output"]])


def build_report(spec: dict[str, Any], scope: dict[str, Any], default_title: str) -> dict[str, Any]:
    """Turn the binding's ``report`` block into a structured result."""
    values = resolve(spec.get("values", {}), scope)
    report: dict[str, Any] = {"title": render_template(spec.get("title", default_title), values) or default_title,
                              "summary": render_template(spec.get("summary", ""), values), "sections": []}
    for sec in spec.get("sections", []):
        out = {"heading": render_template(sec.get("heading", ""), values)}
        for kind in ("table", "items", "fields", "text"):
            if kind in sec:
                content = resolve(sec[kind], scope)
                if kind == "text" and isinstance(content, str):
                    content = render_template(content, values)
                out[kind] = content
        if "columns" in sec:
            out["columns"] = sec["columns"]
        if sec.get("empty"):
            out["empty"] = sec["empty"]
        report["sections"].append(out)
    return report
