"""The scored routing/extraction set: matcher semantics and the offline baseline."""
from workflow_agent.evals import run_eval, value_matches
from workflow_agent.settings import ROOT


def test_value_matching():
    assert value_matches("ORD-1001", " ord-1001 ")
    assert value_matches(10, "10.0") and not value_matches(10, "ten")
    assert value_matches("~online sales", "Drive more online sales")
    assert value_matches(["a", "B"], ["b", "a"])
    assert not value_matches("x", None)


def test_offline_baseline_meets_thresholds(agent):
    report = run_eval(agent, ROOT / "evals" / "routing_extraction.yaml")
    assert report["cases"] >= 40
    assert report["passed"], [r for r in report["rows"] if not r["routed_ok"] or r["input_failures"]]
