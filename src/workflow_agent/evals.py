"""Scored evaluation of routing and input extraction (``python -m workflow_agent --eval``).

Each case in ``evals/routing_extraction.yaml`` names the workflow a request should map to (or
null for out-of-scope requests) and the inputs the request states. Routing and extraction are
scored separately; the command fails when either accuracy is below its threshold, so CI catches
a prompt, model or bindings change that makes the agent worse.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .engine import WorkflowAgent
from .extractor import extract_inputs


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def value_matches(expected: Any, actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(expected, str) and expected.startswith("~"):
        return _norm(expected[1:]) in _norm(actual)
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) < 1e-9
        except (TypeError, ValueError):
            return False
    if isinstance(expected, list):
        got = actual if isinstance(actual, list) else [actual]
        return {_norm(x) for x in expected} == {_norm(x) for x in got}
    return _norm(expected) == _norm(actual)


def run_eval(agent: WorkflowAgent, path: Path) -> dict[str, Any]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = spec["cases"]
    routed_ok = 0
    fields_total = fields_ok = 0
    rows = []
    for case in cases:
        request, expect = case["request"], case.get("expect")
        decision = agent.router.route(request, agent.settings.min_route_confidence)
        ok = decision.workflow_id == expect
        routed_ok += ok
        failures = []
        expected_inputs = case.get("inputs") or {}
        if expected_inputs:
            # extraction is scored against the expected workflow so a routing miss isn't counted twice
            wf = agent.registry.workflows[expect]
            got = extract_inputs(wf, request, agent.llm, [], fill_defaults=False)
            for name, want in expected_inputs.items():
                fields_total += 1
                if value_matches(want, got.get(name)):
                    fields_ok += 1
                else:
                    failures.append(f"{name}: expected {want!r}, got {got.get(name)!r}")
        rows.append({"request": request, "expect": expect, "got": decision.workflow_id,
                     "confidence": decision.confidence, "routed_ok": ok, "input_failures": failures})
    thresholds = spec.get("thresholds") or {}
    report = {
        "mode": "llm" if agent.llm else "offline",
        "cases": len(cases),
        "routing_accuracy": round(routed_ok / len(cases), 4) if cases else 1.0,
        "input_fields": fields_total,
        "input_accuracy": round(fields_ok / fields_total, 4) if fields_total else 1.0,
        "thresholds": thresholds,
        "rows": rows,
    }
    report["passed"] = (report["routing_accuracy"] >= thresholds.get("routing_accuracy", 0)
                        and report["input_accuracy"] >= thresholds.get("input_accuracy", 0))
    return report


def format_report(report: dict[str, Any]) -> str:
    lines = []
    for r in report["rows"]:
        mark = "ok " if r["routed_ok"] and not r["input_failures"] else "BAD"
        lines.append(f"[{mark}] {r['request'][:68]:68} -> {r['got'] or '-'} (expected {r['expect'] or '-'})")
        lines += [f"        {f}" for f in r["input_failures"]]
    t = report["thresholds"]
    lines += ["",
              f"mode: {report['mode']}   cases: {report['cases']}",
              f"routing accuracy: {report['routing_accuracy']:.1%} (threshold {t.get('routing_accuracy', 0):.0%})",
              f"input accuracy:   {report['input_accuracy']:.1%} over {report['input_fields']} fields "
              f"(threshold {t.get('input_accuracy', 0):.0%})",
              "PASSED" if report["passed"] else "FAILED"]
    return "\n".join(lines)
