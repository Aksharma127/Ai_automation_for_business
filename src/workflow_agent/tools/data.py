"""Generic table tools (CSV/XLSX reader, calculator, filter, join, export).

Tables travel between steps as lists of plain dicts so the workflow state stays
JSON-serialisable and easy to show in the execution trace.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from ..expressions import ExpressionError, evaluate
from .base import ToolContext, ToolError, resolve_path, tool

Table = list[dict[str, Any]]


def _clean(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy scalar -> python
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer() and abs(value) < 1e15:  # 120.0 from a column with blanks -> 120
            return int(value)
    return value


def _records(df: pd.DataFrame) -> Table:
    return [{str(k): _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


@tool("load_table", provides=("csv reader", "excel/csv parser", "database reader", "csv/database reader", "file reader"))
def load_table(ctx: ToolContext, path: str, sheet: str | int | None = None) -> Table:
    """Read a CSV, XLSX or JSON file into a list of row dicts."""
    p = resolve_path(ctx, path)
    if not p.exists():
        raise ToolError(f"file not found: {path}")
    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(p)
        elif suffix in {".xlsx", ".xlsm", ".xls"}:
            df = pd.read_excel(p, sheet_name=sheet or 0)
        elif suffix == ".json":
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else [data]
        else:
            raise ToolError(f"unsupported file type {suffix!r} (expected .csv, .xlsx or .json)")
    except (ValueError, OSError, pd.errors.ParserError) as exc:
        raise ToolError(f"could not parse {path}: {exc}") from exc
    if df.empty:
        raise ToolError(f"{path} contains no rows")
    return _records(df)


@tool("load_tables", provides=("csv reader", "file reader"))
def load_tables(ctx: ToolContext, sources: dict[str, str]) -> dict[str, Table]:
    """Read several files at once, returning {name: rows}."""
    return {name: load_table(ctx, path) for name, path in sources.items()}


@tool("load_json", provides=("file reader",))
def load_json(ctx: ToolContext, path: str) -> Any:
    """Read a JSON document."""
    p = resolve_path(ctx, path)
    if not p.exists():
        raise ToolError(f"file not found: {path}")
    return json.loads(p.read_text())


@tool("add_columns", provides=("calculator",))
def add_columns(ctx: ToolContext, table: Table, columns: dict[str, str], params: dict[str, Any] | None = None) -> Table:
    """Add computed columns to every row using safe expressions (the calculator tool).

    Columns are computed in order, so later expressions can use earlier ones. A row whose
    expression fails (e.g. text where a number is expected) gets None and a warning.
    """
    params = params or {}
    out: Table = []
    for i, row in enumerate(table):
        new = dict(row)
        for name, expr in columns.items():
            try:
                new[name] = evaluate(expr, {**params, **new})
            except ExpressionError:
                raise
            except Exception as exc:  # bad data in one row should not kill the workflow
                new[name] = None
                ctx.note(f"row {i + 1} ({row.get('sku', '?')}): could not compute {name}: {exc}")
        out.append(new)
    return out


@tool("filter_rows", provides=("calculator", "data validation"))
def filter_rows(ctx: ToolContext, table: Table, condition: str, params: dict[str, Any] | None = None) -> Table:
    """Keep rows where the condition expression is true (the decision step)."""
    params = params or {}
    kept = []
    for row in table:
        try:
            if evaluate(condition, {**params, **row}):
                kept.append(row)
        except ExpressionError:
            raise
        except Exception as exc:
            ctx.note(f"skipped row {row.get('sku', '?')} in filter: {exc}")
    return kept


@tool("join_tables", provides=("csv reader",))
def join_tables(ctx: ToolContext, left: Table, right: Table, left_on: str, right_on: str) -> dict[str, Table]:
    """Match two tables on a key (case/whitespace-insensitive) and report unmatched rows on both sides."""

    def key(v: Any) -> str:
        return str(v).strip().upper() if v is not None else ""

    index: dict[str, dict[str, Any]] = {}
    for r in right:
        k = key(r.get(right_on))
        if k and k in index:
            ctx.note(f"duplicate key {k} in right table; keeping the first row")
        index.setdefault(k, r)
    matched, unmatched_left, used = [], [], set()
    for l in left:
        k = key(l.get(left_on))
        if k in index:
            matched.append({**l, **index[k]})
            used.add(k)
        else:
            unmatched_left.append(l)
    unmatched_right = [r for r in right if key(r.get(right_on)) not in used]
    return {"matched": matched, "unmatched_left": unmatched_left, "unmatched_right": unmatched_right}


@tool("sort_rows")
def sort_rows(ctx: ToolContext, table: Table, by: str, descending: bool = False) -> Table:
    """Sort rows by a column (missing values last)."""
    present = [r for r in table if r.get(by) is not None]
    missing = [r for r in table if r.get(by) is None]
    return sorted(present, key=lambda r: r[by], reverse=descending) + missing


@tool("export_table", provides=("reporting", "export"))
def export_table(ctx: ToolContext, table: Table, filename: str, columns: list[str] | None = None) -> str:
    """Write rows to a CSV file under the output directory and return its path."""
    out = ctx.output_dir / "files" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = columns or list(dict.fromkeys(k for r in table for k in r))
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(table)
    try:
        return str(out.relative_to(ctx.root))
    except ValueError:
        return str(out)
