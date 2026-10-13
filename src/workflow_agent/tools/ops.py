"""Workflow performance analytics over execution logs."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from ..expressions import evaluate
from .base import ToolContext, tool
from .data import Table


def _runs(logs: Table) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for r in logs:
        run = runs.setdefault(r["run_id"], {"workflow_id": r["workflow_id"], "workflow_name": r["workflow_name"],
                                            "failed": False, "duration": 0.0})
        run["duration"] += float(r.get("duration_sec") or 0)
        run["failed"] |= str(r.get("status")).lower() != "success"
    return runs


@tool("run_outcomes", provides=("calculator",))
def run_outcomes(ctx: ToolContext, logs: Table) -> Table:
    """Success and failure rate per workflow (a run fails if any step failed)."""
    by_wf: dict[tuple, list] = defaultdict(list)
    for run in _runs(logs).values():
        by_wf[(run["workflow_id"], run["workflow_name"])].append(run)
    out = []
    for (wid, name), runs in sorted(by_wf.items()):
        failed = sum(r["failed"] for r in runs)
        out.append({"workflow_id": wid, "workflow_name": name, "runs": len(runs), "failed_runs": failed,
                    "success_rate": round(1 - failed / len(runs), 3), "failure_rate": round(failed / len(runs), 3)})
    return out


@tool("run_durations", provides=("calculator",))
def run_durations(ctx: ToolContext, logs: Table, stats: Table) -> Table:
    """Add average and max successful-run duration (seconds) to each workflow's stats."""
    durs: dict[str, list[float]] = defaultdict(list)
    for run in _runs(logs).values():
        if not run["failed"]:
            durs[run["workflow_id"]].append(run["duration"])
    return [{**s, "avg_duration_sec": round(mean(durs[s["workflow_id"]]), 2) if durs[s["workflow_id"]] else None,
             "max_duration_sec": round(max(durs[s["workflow_id"]]), 2) if durs[s["workflow_id"]] else None}
            for s in stats]


@tool("frequent_errors", provides=("reporting",))
def frequent_errors(ctx: ToolContext, logs: Table, top_n: int = 5) -> Table:
    """Most common error messages, with the workflow and step where they occur."""
    c: Counter = Counter()
    for r in logs:
        if r.get("error_message"):
            c[(r["workflow_id"], r["step"], r["error_message"])] += 1
    return [{"workflow_id": w, "step": s, "error": e, "occurrences": n} for (w, s, e), n in c.most_common(top_n)]


@tool("slow_steps", provides=("reporting",))
def slow_steps(ctx: ToolContext, logs: Table, top_n: int = 5) -> Table:
    """Steps with the highest average duration."""
    d: dict[tuple, list[float]] = defaultdict(list)
    for r in logs:
        d[(r["workflow_id"], r["step"])].append(float(r.get("duration_sec") or 0))
    rows = [{"workflow_id": w, "step": s, "avg_sec": round(mean(v), 2), "samples": len(v)} for (w, s), v in d.items()]
    return sorted(rows, key=lambda r: r["avg_sec"], reverse=True)[:top_n]


ERROR_ADVICE = {
    "timeout": "add retries with exponential backoff and a circuit breaker around the external API; cache recent responses",
    "ratelimit": "throttle/batch LLM calls, add retry-after handling and consider a fallback model",
    "validation": "validate files at upload time and send the vendor an automated error report",
    "parse": "detect encoding/format before parsing and support the failing format explicitly",
    "notfound": "treat 'not found' as a user-facing outcome (ask for another identifier) rather than a failure",
    "keyerror": "add schema checks for required columns before processing",
}


@tool("performance_recommendations", provides=("reporting",))
def performance_recommendations(ctx: ToolContext, stats: Table, errors: Table, slow: Table, flag_if: str,
                                params: dict[str, Any]) -> dict[str, Any]:
    """Flag workflows breaching thresholds and recommend fixes based on their errors and slow steps."""
    flagged, recs = [], []
    for s in stats:
        reasons = []
        env = {**params, **s, "avg_duration_sec": s.get("avg_duration_sec") or 0}
        if evaluate(flag_if, env):
            if s["failure_rate"] > params["max_failure_rate"]:
                reasons.append(f"failure rate {s['failure_rate']:.1%} > {params['max_failure_rate']:.0%}")
            if env["avg_duration_sec"] > params["max_avg_duration_sec"]:
                reasons.append(f"avg time {env['avg_duration_sec']}s > {params['max_avg_duration_sec']}s")
            flagged.append({**s, "flag_reasons": "; ".join(reasons)})
    for f in flagged:
        wid = f["workflow_id"]
        errs = [e for e in errors if e["workflow_id"] == wid]
        for e in errs[:2]:
            key = e["error"].split(":")[0].lower().replace("error", "").replace("_", "") or "other"
            advice = next((v for k, v in ERROR_ADVICE.items() if k in key or k in e["error"].lower().replace(" ", "")),
                          "investigate the root cause and add a regression test")
            recs.append(f"{wid} {f['workflow_name']}: '{e['error']}' at step '{e['step']}' ({e['occurrences']}x) - {advice}.")
        steps = [s for s in slow if s["workflow_id"] == wid]
        if steps and "avg time" in f["flag_reasons"]:
            st = steps[0]
            recs.append(f"{wid} {f['workflow_name']}: step '{st['step']}' averages {st['avg_sec']}s - "
                        "parallelise or cache this step, or move it to a background job.")
    if not flagged:
        recs.append("All workflows are within thresholds; keep monitoring.")
    flagged.sort(key=lambda r: r["failure_rate"], reverse=True)
    ranked = sorted(stats, key=lambda r: (r["failure_rate"], r.get("avg_duration_sec") or 0), reverse=True)
    return {"flagged": flagged, "recommendations": recs, "ranked": ranked}
