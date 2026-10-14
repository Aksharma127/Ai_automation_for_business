"""The agent: a LangGraph state machine that runs any workflow in the registry.

    understand_request ──(no match)──► clarify ──► await_input ─┐
            │                                         ▲          │ (user replies:
            ▼                                         │          │  re-route or
      extract_inputs                                  │          │  re-extract inputs)
            │                                   (needs input)    │
            ▼                                         │          │
    ┌─► execute_step ─────────────────────────────────┘ ◄────────┘
    └──────┘ next step
            │ done / escalated / failed
            ▼
        finalize ──► END

Nothing in this file knows about a specific workflow: steps, tools, arguments, decision rules
and report layout all come from the registry (Excel + YAML bindings).

Production behaviour:
* ``await_input`` uses LangGraph ``interrupt()`` + a checkpointer (SQLite/PostgreSQL), so a run
  that asks the user something is paused and continues with ``resume(run_id, answer)``,
  even from another process or after a restart.
* every tool call has a timeout, retries with backoff and an on_error policy
* each run is recorded (steps, status, LLM calls, tokens, cost, duration) in the RunStore
* structured logs carry the run id; OpenTelemetry spans wrap runs and steps
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import operator
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import llm as llm_api
from .extractor import extract_inputs
from .integrations import build_services
from .observability import current_run_id, log, span
from .registry import Registry, StepBinding, load_registry
from .router import make_router
from .settings import ROOT, Settings, get_settings
from .storage import RunStore
from .tools import ToolContext, call_tool
from .tools.base import ToolError, TransientToolError, WorkflowHalt
from .tools.content import render_template

MAX_REPLIES = 5
_current_ctx: contextvars.ContextVar[ToolContext] = contextvars.ContextVar("tool_ctx")


class AgentState(TypedDict, total=False):
    request: str
    run_id: str
    attachments: list[str]
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
    notes: Annotated[list[str], operator.add]
    replies: int


class RunNotFound(KeyError):
    pass


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

def make_checkpointer(url: str) -> Any:
    """LangGraph checkpointer for pausable runs: memory, SQLite or PostgreSQL."""
    if not url or url == "memory":
        return InMemorySaver()
    if url.startswith("sqlite"):
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = url.split("sqlite:///", 1)[-1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        saver = SqliteSaver(sqlite3.connect(path.replace(".db", "") + ".checkpoints.db", check_same_thread=False))
        saver.setup()
        return saver
    if url.startswith(("postgres://", "postgresql://")):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(url, max_size=10, open=True, kwargs={"autocommit": True, "prepare_threshold": 0,
                                                        "row_factory": dict_row})
        pg_saver = PostgresSaver(cast(Any, pool))  # pool yields dict rows (row_factory above)
        pg_saver.setup()
        return pg_saver
    raise ValueError(f"unsupported CHECKPOINT_URL scheme: {url.split(':', 1)[0]}")


class WorkflowAgent:
    def __init__(self, settings: Settings | None = None, llm: Any = "auto", registry: Registry | None = None,
                 store: RunStore | None = None, checkpointer: Any = None, services: Any = None):
        self.settings = settings or get_settings()
        self.llm = llm_api.get_llm(self.settings) if llm == "auto" else llm
        self.registry = registry or load_registry(self.settings.workflow_excel, self.settings.bindings_file)
        self.router = make_router(self.registry.executable(), self.llm)
        self.store = store if store is not None else RunStore(self.settings.database_url)
        self.services = services or build_services(self.settings, ROOT)
        cp_url = self.settings.checkpoint_url or self.settings.database_url
        self.checkpointer = checkpointer if checkpointer is not None else make_checkpointer(cp_url)
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="tool")
        self.graph = self._build_graph()

    # -- graph -----------------------------------------------------------------------------
    def _build_graph(self) -> Any:
        g = StateGraph(AgentState)
        nodes: dict[str, Any] = {  # Any: LangGraph's node protocols expect the parameter to be named `state`
            "understand_request": self._understand, "clarify": self._clarify, "extract_inputs": self._extract,
            "execute_step": self._execute_step, "await_input": self._await_input, "finalize": self._finalize,
        }
        for name, fn in nodes.items():
            g.add_node(name, fn)
        g.add_edge(START, "understand_request")
        g.add_conditional_edges("understand_request", lambda s: "extract_inputs" if s.get("workflow_id") else "clarify")
        g.add_conditional_edges("clarify", lambda s: "await_input" if s.get("replies", 0) < MAX_REPLIES else END)
        g.add_edge("extract_inputs", "execute_step")
        g.add_conditional_edges("execute_step", self._next)
        g.add_conditional_edges("await_input", lambda s: "execute_step" if s.get("workflow_id") else "understand_request")
        g.add_edge("finalize", END)
        return g.compile(checkpointer=self.checkpointer)

    def _next(self, s: AgentState) -> str:
        wf = self.registry.get(s["workflow_id"])  # type: ignore[arg-type]
        if s["status"] == "running" and s["step_index"] < len(wf.steps):
            return "execute_step"
        if s["status"] == "needs_input" and s.get("replies", 0) < MAX_REPLIES:
            return "await_input"
        return "finalize"

    @staticmethod
    def _drain_notes() -> list[str]:
        ctx = _current_ctx.get()
        notes, ctx.notes[:] = list(ctx.notes), []
        return notes

    # -- nodes -----------------------------------------------------------------------------
    def _understand(self, s: AgentState) -> AgentState:
        with span("workflow.route"):
            d = self.router.route(s["request"], self.settings.min_route_confidence)
        route = {"workflow_id": d.workflow_id, "confidence": d.confidence, "reasoning": d.reasoning,
                 "method": d.method, "candidates": d.candidates}
        log.info("routed", extra={"workflow_id": d.workflow_id, "confidence": d.confidence, "method": d.method})
        if not d.workflow_id:
            return {"route": route, "workflow_id": None, "status": "no_workflow"}
        wf = self.registry.get(d.workflow_id)
        return {"route": route, "workflow_id": wf.id, "workflow_name": wf.name, "status": "running",
                "step_index": 0, "memory": {}}

    def _clarify(self, s: AgentState) -> AgentState:
        options = "\n".join(f"  - {w.name}: {w.trigger}" for w in self.registry.executable())
        guess = s["route"]["candidates"][:2]
        hint = (" Did you mean " + " or ".join(c["name"] for c in guess) + "?") if guess and guess[0]["score"] > 0 else ""
        msg = f"I couldn't confidently match your request to a workflow.{hint}\nI can help with:\n{options}"
        return {"message": msg, "answer": msg}

    def _extract(self, s: AgentState) -> AgentState:
        wf = self.registry.get(s["workflow_id"])  # type: ignore[arg-type]
        notes: list[str] = []
        inputs = extract_inputs(wf, s["request"], self.llm, notes)
        attachments = s.get("attachments") or []
        if attachments:
            upload_inputs = [k for k, v in wf.inputs.items() if v.get("upload")]
            if upload_inputs:
                inputs[upload_inputs[0]] = attachments[0]
                notes.append(f"using the uploaded file for {upload_inputs[0]}")
            else:
                notes.append(f"{wf.name} does not take a file; the upload was ignored")
        inputs["request"] = s["request"]
        return {"inputs": inputs, "notes": notes + self._drain_notes()}

    def _await_input(self, s: AgentState) -> AgentState:
        """Pause the run until the user answers (LangGraph interrupt), then apply the answer."""
        answer = str(interrupt({"question": s.get("message"), "missing": (s.get("memory") or {}).get("_halt")}))
        reply_rec = {"n": 0, "step": "User replied", "tool": "-", "status": "user_reply", "output": answer[:200],
                     "ms": 0.0, "attempts": 0}
        combined = f"{s['request']}\n{answer}"
        replies = s.get("replies", 0) + 1
        if not s.get("workflow_id"):  # answer to "which workflow?": route again
            return {"request": combined, "replies": replies, "trace": [reply_rec], "message": None}
        wf = self.registry.get(s["workflow_id"])  # type: ignore[arg-type]
        notes: list[str] = []
        new_inputs = extract_inputs(wf, answer, self.llm, notes, fill_defaults=False)
        inputs = {**s["inputs"], **new_inputs, "request": combined}
        # restart the step list: earlier steps may depend on the newly supplied inputs
        return {"request": combined, "inputs": inputs, "step_index": 0, "memory": {}, "status": "running",
                "message": None, "replies": replies, "trace": [reply_rec], "notes": notes + self._drain_notes()}

    def _execute_step(self, s: AgentState) -> AgentState:
        ctx = _current_ctx.get()
        wf = self.registry.get(s["workflow_id"])  # type: ignore[arg-type]
        i = s["step_index"]
        step = wf.steps[i]
        memory = dict(s["memory"])
        scope = {"inputs": s["inputs"], **memory}
        rec: dict[str, Any] = {"n": i + 1, "step": step.label, "tool": step.tool, "attempts": 0}
        t0 = time.perf_counter()
        status, message = "running", None
        with span("workflow.step", workflow_id=wf.id, step=step.label, tool=step.tool) as sp:
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
                    if not isinstance(exc, (ToolError, TransientToolError)):
                        log.exception("unexpected tool error", extra={"tool": step.tool})
            rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if sp is not None:
                sp.set_attribute("workflow.status", rec["status"])
        log.info("step finished", extra={"workflow_id": wf.id, "step_no": i + 1, "tool": rec["tool"],
                                         "status": rec["status"], "ms": rec["ms"], "attempts": rec["attempts"]})
        if status == "running" and i + 1 == len(wf.steps):
            status = "completed"
        return {"memory": memory, "step_index": i + 1, "trace": [rec], "status": status, "message": message,
                "notes": self._drain_notes()}

    def _call_tool_with_timeout(self, name: str, args: dict[str, Any], ctx: ToolContext) -> Any:
        # copy the context so LangChain callbacks (LLM budget, tracing) follow the call into the thread
        fut = self._pool.submit(contextvars.copy_context().run, call_tool, name, args, ctx)
        try:
            return fut.result(timeout=self.settings.step_timeout_sec)
        except concurrent.futures.TimeoutError as exc:
            fut.cancel()
            raise TransientToolError(f"{name} timed out after {self.settings.step_timeout_sec:g}s") from exc

    def _call_with_policy(self, step: StepBinding, args: dict[str, Any], ctx: ToolContext, rec: dict) -> Any:
        last: Exception | None = None
        for attempt in range(step.retries + 1):
            rec["attempts"] = attempt + 1
            try:
                return self._call_tool_with_timeout(step.tool, args, ctx)
            except TransientToolError as exc:
                last = exc
                rec.setdefault("retries", []).append(str(exc))
                log.warning("transient tool failure", extra={"tool": step.tool, "attempt": attempt + 1, "error": str(exc)})
                if attempt < step.retries:
                    time.sleep(min(0.05 * 2 ** attempt, 0.5))  # exponential backoff
        if step.on_error == "degrade" and step.fallback_tool:
            rec["status"] = "degraded"
            rec["tool"] = f"{step.tool} → {step.fallback_tool}"
            return self._call_tool_with_timeout(step.fallback_tool, args, ctx)
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
            except Exception as exc:  # a bad describe template must never fail the step
                log.debug("describe template failed", extra={"error": repr(exc)})
        return summarize_output(out)

    def _finalize(self, s: AgentState) -> AgentState:
        wf = self.registry.get(s["workflow_id"])  # type: ignore[arg-type]
        if s["status"] != "completed":
            return {"result": None, "answer": s.get("message"), "notes": self._drain_notes()}
        notes: list[str] = []
        try:
            report = build_report(wf.report, {"inputs": s["inputs"], **s["memory"]}, wf.name)
        except Exception as exc:
            notes.append(f"report layout error: {exc}")
            report = {"title": wf.name, "summary": "Completed.", "sections": []}
        answer = report["summary"]
        if self.llm is not None and wf.report.get("narrate", True):
            try:
                answer = llm_api.ask_text(
                    self.llm, "Write a 1-3 sentence answer to the user's request using ONLY the result data. "
                              "No markdown headings.",
                    f"Request:\n{llm_api.data(s['request'], 'request')}\n"
                    f"Result:\n{llm_api.data(llm_api.as_json(report)[:6000], 'result')}")
            except Exception as exc:
                notes.append(f"LLM summary unavailable ({type(exc).__name__})")
        return {"result": report, "answer": answer, "notes": notes + self._drain_notes()}

    # -- public API --------------------------------------------------------------------------
    def run(self, request: str, *, attachments: list[str] | None = None, principal: str | None = None,
            run_id: str | None = None) -> dict[str, Any]:
        """Start a run. If the agent needs more information the run pauses (``awaiting_reply``)."""
        request = (request or "").strip()
        if not request:
            raise ValueError("request is empty")
        if len(request) > self.settings.max_request_chars:
            raise ValueError(f"request is longer than {self.settings.max_request_chars} characters")
        run_id = run_id or f"RUN-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        initial = {"request": request, "run_id": run_id, "attachments": attachments or [], "trace": [], "notes": [],
                   "replies": 0}
        return self._invoke(initial, run_id, principal)

    def resume(self, run_id: str, answer: str, *, principal: str | None = None) -> dict[str, Any]:
        """Continue a paused run with the user's answer."""
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("answer is empty")
        if len(answer) > self.settings.max_request_chars:
            raise ValueError(f"answer is longer than {self.settings.max_request_chars} characters")
        record = self.store.get_run(run_id)
        if record is None or (principal is not None and record.get("principal") not in (None, principal)):
            raise RunNotFound(run_id)
        snapshot = self.graph.get_state({"configurable": {"thread_id": run_id}})
        if not snapshot.next:
            raise ValueError(f"run {run_id} is not waiting for a reply (status: {record['status']})")
        return self._invoke(Command(resume=answer), run_id, principal)

    def _invoke(self, payload: Any, run_id: str, principal: str | None) -> dict[str, Any]:
        cfg = {"configurable": {"thread_id": run_id}}
        budget = llm_api.RunBudget(llm_api.model_name(self.llm), self.settings.max_llm_calls_per_run,
                                   self.settings.max_llm_cost_per_run_usd, self.settings.llm_price_input,
                                   self.settings.llm_price_output)
        ctx = ToolContext(llm=self.llm, root=ROOT, output_dir=self.settings.output_dir, run_id=run_id,
                          services=self.services, store=self.store,
                          allowed_dirs=tuple(Path(d) if Path(d).is_absolute() else ROOT / d
                                             for d in self.settings.allowed_data_dirs) + (self.settings.upload_dir,),
                          allowed_hosts=self.settings.allowed_source_hosts, http_timeout=self.settings.http_timeout_sec)
        tok_ctx, tok_run = _current_ctx.set(ctx), current_run_id.set(run_id)
        t0 = time.perf_counter()
        try:
            with span("workflow.run", run_id=run_id):
                self.graph.invoke(payload, config={**cfg, "callbacks": [budget]})
        finally:
            _current_ctx.reset(tok_ctx)
            current_run_id.reset(tok_run)
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        snapshot = self.graph.get_state(cfg)
        state: dict[str, Any] = dict(snapshot.values)
        state["awaiting_reply"] = bool(snapshot.next)
        if state["awaiting_reply"] and not state.get("answer") or state["awaiting_reply"] and state.get("status") == "needs_input":
            state["answer"] = state.get("message")
        state["mode"] = llm_api.describe(self.llm)
        state["usage"] = budget.snapshot()
        state["duration_ms"] = duration_ms
        try:
            self.store.save_run(state, principal=principal, usage=state["usage"], duration_ms=duration_ms)
        except Exception:  # history is important but must never lose the user's answer
            log.exception("could not save run history")
        log.info("run finished", extra={"workflow_id": state.get("workflow_id"), "status": state.get("status"),
                                        "awaiting_reply": state["awaiting_reply"], "ms": duration_ms,
                                        "llm_calls": budget.calls, "cost_usd": budget.cost_usd})
        return state

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.store.close()


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
