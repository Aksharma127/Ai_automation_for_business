"""A tiny, safe expression evaluator: the "calculator" behind declarative workflow rules.

Business rules from the Excel "Decision_Logic" column are written in the bindings as
expressions such as ``current_stock < minimum_stock`` or ``pct_diff > tolerance_pct``.
Only arithmetic, comparisons, boolean logic, ``x if c else y`` and a whitelist of
functions are allowed; there is no attribute access and no ``eval``.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any, Mapping


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None and not (isinstance(v, float) and math.isnan(v)) and v != "":
            return v
    return None


def _safe_div(a: Any, b: Any, default: Any = None) -> Any:
    try:
        return a / b if b else default
    except TypeError:
        return default


FUNCS = {
    "abs": abs, "max": max, "min": min, "round": round, "int": int, "float": float, "len": len,
    "ceil": math.ceil, "floor": math.floor, "coalesce": _coalesce, "safe_div": _safe_div,
    "lower": lambda s: str(s).lower(), "is_missing": lambda v: _coalesce(v) is None,
}

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}


class ExpressionError(ValueError):
    pass


def evaluate(expr: str, variables: Mapping[str, Any]) -> Any:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expr!r}: {exc.msg}") from exc
    return _eval(tree.body, variables, expr)


def _eval(node: ast.AST, env: Mapping[str, Any], src: str) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise ExpressionError(f"unknown name {node.id!r} in {src!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, env, src), _eval(node.right, env, src))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env, src))
    if isinstance(node, ast.BoolOp):
        vals = (_eval(v, env, src) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, src)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env, src)
            if type(op) not in _CMP or not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env, src) if _eval(node.test, env, src) else _eval(node.orelse, env, src)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
        return FUNCS[node.func.id](*(_eval(a, env, src) for a in node.args))
    if isinstance(node, ast.Subscript):  # dict/list lookup, e.g. intent_weights[intent]
        container = _eval(node.value, env, src)
        key = _eval(node.slice, env, src)
        try:
            return container[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"no entry {key!r}") from exc
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, env, src) for e in node.elts]
    raise ExpressionError(f"unsupported syntax in {src!r}: {type(node).__name__}")
