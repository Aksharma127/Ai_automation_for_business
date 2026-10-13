import pytest

from workflow_agent.expressions import ExpressionError, evaluate


def test_business_rules():
    assert evaluate("current_stock < minimum_stock", {"current_stock": 3, "minimum_stock": 5})
    assert evaluate("max(ceil(t * 2 - s), 0)", {"t": 10, "s": 25}) == 0
    assert evaluate("w[i] * 2", {"w": {"a": 1.5}, "i": "a"}) == 3.0
    assert evaluate("'High' if x >= 3 else 'Low'", {"x": 4}) == "High"
    assert evaluate("coalesce(None, 7)", {}) == 7


@pytest.mark.parametrize("expr", ["__import__('os')", "x.__class__", "open('f')", "(lambda: 1)()"])
def test_unsafe_code_is_rejected(expr):
    with pytest.raises(ExpressionError):
        evaluate(expr, {"x": 1})
