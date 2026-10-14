"""Human-readable rendering of an agent run (console and saved Markdown outputs)."""
from __future__ import annotations

from typing import Any

ICON = {"ok": "✓", "degraded": "⚠", "error-continued": "⚠", "failed": "✗", "needs_input": "?", "escalated": "↑",
        "user_reply": "↩"}
STATUS_LABEL = {
    "completed": "Completed", "needs_input": "Needs more information", "escalated": "Escalated to a human",
    "failed": "Failed", "no_workflow": "No matching workflow",
}


def _cell(v: Any) -> str:
    if isinstance(v, float):
        v = round(v, 2)
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")


def md_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    if not rows:
        return ""
    cols = columns or list(dict.fromkeys(k for r in rows for k in r))
    head = "| " + " | ".join(cols) + " |\n| " + " | ".join("---" for _ in cols) + " |\n"
    return head + "\n".join("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows)


def render_result(result: dict[str, Any]) -> str:
    parts = [f"**{result['title']}**"]
    if result.get("summary"):
        parts.append(result["summary"])
    for sec in result.get("sections", []):
        body = ""
        if "table" in sec:
            t = sec["table"]
            t = [t] if isinstance(t, dict) else (t or [])
            body = md_table(t, sec.get("columns")) if t else f"_{sec.get('empty', 'None.')}_"
        elif "items" in sec:
            items = sec["items"] or []
            body = "\n".join(f"- {_cell(i)}" for i in items) if items else f"_{sec.get('empty', 'None.')}_"
        elif "fields" in sec:
            body = "\n".join(f"- **{str(k).strip()}:** {_cell(v) if v not in (None, '', []) else '_not provided_'}"
                             for k, v in (sec["fields"] or {}).items())
        elif "text" in sec:
            body = str(sec["text"] or sec.get("empty", ""))
        parts.append(f"*{sec['heading']}*\n\n{body}" if sec.get("heading") else body)
    return "\n\n".join(parts)


def render_run(state: dict[str, Any]) -> str:
    route = state.get("route", {})
    lines = [f"**User Request:** {state['request']}", ""]
    if state.get("workflow_id"):
        lines.append(f"**Selected Workflow:** {state['workflow_id']} · {state['workflow_name']}")
    else:
        lines.append("**Selected Workflow:** none")
    lines.append(f"**Routing:** {route.get('method')} · confidence {route.get('confidence')} · {route.get('reasoning')}")
    lines.append(f"**Mode:** {state.get('mode')}")
    if state.get("inputs"):
        shown = {k: v for k, v in state["inputs"].items() if k != "request" and v not in (None, "", [], {})}
        lines.append("**Inputs:** " + ("; ".join(f"{k}={_cell(v)}" for k, v in shown.items()) or "none"))
    if state.get("trace"):
        lines += ["", "**Steps Executed:**"]
        for t in state["trace"]:
            extra = f" · retried {len(t['retries'])}x" if t.get("retries") else ""
            if t["status"] == "user_reply":
                lines.append(f"{ICON['user_reply']} User replied: {t['output']}")
                continue
            lines.append(f"{t['n']}. {ICON.get(t['status'], '•')} {t['step']} — `{t['tool']}` → {t['output']}"
                         f" ({t['ms']} ms{extra})")
    status = str(STATUS_LABEL.get(state.get("status") or "", state.get("status")))
    if state.get("awaiting_reply"):
        status += f" (paused; reply with `--reply {state['run_id']} \"...\"` or POST /v1/runs/{state['run_id']}/reply)"
    lines += ["", f"**Status:** {status}", "", "**Result:**", ""]
    if state.get("result"):
        if state.get("answer") and state["answer"] != state["result"].get("summary"):
            lines += [state["answer"], ""]
        lines.append(render_result(state["result"]))
    else:
        lines.append(state.get("answer") or state.get("message") or "")
    if state.get("notes"):
        lines += ["", "**Notes / handled issues:**"] + [f"- {n}" for n in dict.fromkeys(state["notes"])]
    return "\n".join(lines)
