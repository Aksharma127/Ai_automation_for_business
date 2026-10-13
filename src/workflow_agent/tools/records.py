"""Generic record-level tools: validation, lookup, cleaning, ranking and selection.

These are shared by several workflows; the workflow-specific rules are passed in as
arguments from the YAML bindings.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from .. import llm as llm_api
from ..expressions import evaluate
from .base import Escalate, NeedsInput, ToolContext, ToolError, resolve_path, tool
from .data import Table, export_table, load_json, load_table

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


def _human_join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


@tool("collect_fields", provides=("text validation", "data validation"))
def collect_fields(ctx: ToolContext, required: list[str], optional: list[str] | None = None,
                   base_file: str | None = None, overrides: dict[str, Any] | None = None,
                   halt_if_missing: bool = True, ask: str | None = None,
                   checks: list[dict[str, str]] | None = None, base_key: str | None = None) -> dict[str, Any]:
    """Merge a base record (file) with values from the request and validate required fields.

    Missing required fields stop the workflow with a request for those fields (when
    ``halt_if_missing``); missing optional fields are reported, never invented.
    """
    record: dict[str, Any] = {}
    overrides = overrides or {}
    if base_file:
        data = load_json(ctx, base_file)
        data = data if isinstance(data, dict) else {}
        # the request names a different item than the base file: don't mix their attributes
        if base_key and not _missing(overrides.get(base_key)) and \
                str(overrides[base_key]).strip().lower() != str(data.get(base_key, "")).strip().lower():
            data = {}
        record.update(data)
    for k, v in overrides.items():
        if not _missing(v):
            record[k] = v
    optional = optional or []
    for f in required + optional:  # every declared field exists (None = not provided)
        record.setdefault(f, None)
    missing_required = [f for f in required if _missing(record.get(f))]
    missing_optional = [f for f in optional if _missing(record.get(f))]
    if missing_required and halt_if_missing:
        names = _human_join([f.replace("_", " ") for f in missing_required])
        raise NeedsInput((ask or "Please provide: {missing}.").format(missing=names), missing_required)
    for check in checks or []:  # cross-field business rules, e.g. end date after start date
        env = {f: record.get(f) for f in required + optional} | record
        if not missing_required and evaluate(check["fail_if"], env):
            raise NeedsInput(check["ask"].format(**env))
    return {"record": record, "missing": missing_required + missing_optional,
            "present": [f for f in required + optional if not _missing(record.get(f))]}


@tool("validate_identifier", provides=("data validation",))
def validate_identifier(ctx: ToolContext, order_id: str | None = None, email: str | None = None,
                        id_pattern: str = r"^ORD-\d+$") -> dict[str, str]:
    """Check that the request contains a well-formed order ID or customer email."""
    if order_id:
        oid = re.sub(r"^ORD[-\s#]*", "ORD-", order_id.strip().upper())
        if oid.isdigit():
            oid = f"ORD-{oid}"
        if re.match(id_pattern, oid):
            return {"field": "order_id", "value": oid}
        if not email:
            raise NeedsInput(f"'{order_id}' is not a valid order ID (expected e.g. ORD-1001). "
                             "Please share a valid order ID or the email used for the order.", ["order_id"])
    if email:
        if EMAIL_RE.match(email.strip()):
            return {"field": "customer_email", "value": email.strip().lower()}
        raise NeedsInput(f"'{email}' is not a valid email address. Please share the order ID or a valid email.", ["email"])
    raise NeedsInput("Please provide an order ID (e.g. ORD-1001) or the customer email used for the order.",
                     ["order_id", "email"])


@tool("find_records", provides=("order database/api", "database reader", "employee/task database"))
def find_records(ctx: ToolContext, path: str, field: str, value: Any, if_none: str) -> Table:
    """Look up records in a (simulated) database file where field == value (case-insensitive)."""
    rows = load_table(ctx, path)
    hits = [r for r in rows if str(r.get(field, "")).strip().lower() == str(value).strip().lower()]
    if not hits:
        raise NeedsInput(if_none.format(value=value), [field])
    return hits


@tool("pick_fields")
def pick_fields(ctx: ToolContext, records: Table, fields: list[str]) -> Table:
    """Keep only the listed fields of each record."""
    return [{f: r.get(f) for f in fields} for r in records]


@tool("query_table", provides=("product data reader", "csv reader"))
def query_table(ctx: ToolContext, path: str, condition: str = "True", params: dict[str, Any] | None = None,
                columns: list[str] | None = None, if_none: str | None = None) -> Table:
    """Load a table and return the rows matching a condition (optionally only some columns)."""
    rows = [r for r in load_table(ctx, path) if evaluate(condition, {**(params or {}), **r})]
    if not rows and if_none:
        raise NeedsInput(if_none.format(**(params or {})))
    return [{c: r.get(c) for c in columns} for r in rows] if columns else rows


# --- column detection / cleaning (vendor files) -------------------------------------------

def _norm_header(h: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(h).lower()).strip()


class _HeaderMap(BaseModel):
    mapping: dict[str, str] = Field(description="raw header -> canonical name, only for confident matches")


@tool("detect_columns", provides=("excel/csv parser", "data validation"), uses_llm=True)
def detect_columns(ctx: ToolContext, table: Table, canonical: dict[str, list[str]]) -> dict[str, Any]:
    """Map raw file headers to canonical column names using synonyms (LLM for leftovers)."""
    headers = list(dict.fromkeys(k for r in table for k in r))
    mapping: dict[str, str] = {}
    for h in headers:
        nh = _norm_header(h)
        for canon, synonyms in canonical.items():
            cands = [_norm_header(canon)] + [_norm_header(s) for s in synonyms]
            if canon not in mapping.values() and any(re.search(rf"\b{re.escape(c)}\b", nh) for c in cands):
                mapping[h] = canon
                break
    unmapped = [h for h in headers if h not in mapping]
    if unmapped and ctx.llm is not None:
        try:
            res = llm_api.ask_structured(
                ctx.llm, _HeaderMap,
                "You map spreadsheet headers to a canonical schema. Only map when confident.",
                f"Canonical columns: {list(canonical)}\nUnmapped headers: {unmapped}")
            for raw, canon in res.mapping.items():
                if raw in unmapped and canon in canonical and canon not in mapping.values():
                    mapping[raw] = canon
        except Exception as exc:  # LLM is an enhancement here, never a requirement
            ctx.note(f"LLM header mapping unavailable ({type(exc).__name__}); used synonym rules only")
    missing = [c for c in canonical if c not in mapping.values()]
    return {"mapping": mapping, "unmapped": [h for h in headers if h not in mapping], "missing_canonical": missing}


@tool("rename_columns", provides=("excel/csv parser",))
def rename_columns(ctx: ToolContext, table: Table, mapping: dict[str, str], keep_unmapped: bool = True) -> Table:
    """Rename columns to canonical names, trim text values and drop fully empty rows."""
    out = []
    for i, row in enumerate(table):
        new = {"source_row": i + 2}  # spreadsheet row number (row 1 is the header)
        for k, v in row.items():
            if k in mapping or keep_unmapped:
                new[mapping.get(k, _norm_header(k).replace(" ", "_"))] = v.strip() if isinstance(v, str) else v
        if all(_missing(v) for k, v in new.items() if k != "source_row"):
            ctx.note("dropped a completely empty row")
            continue
        out.append(new)
    return out


@tool("validate_rows", provides=("data validation",))
def validate_rows(ctx: ToolContext, table: Table, required: list[str], numeric: dict[str, dict[str, float]] | None = None,
                  uppercase: list[str] | None = None) -> Table:
    """Annotate each row with blocking errors (missing required fields) and non-blocking warnings."""
    out = []
    for i, row in enumerate(table, start=1):
        r = dict(row)
        for col in uppercase or []:
            if isinstance(r.get(col), str):
                r[col] = r[col].upper()
        errors = [f"missing {f}" for f in required if _missing(r.get(f))]
        warnings = []
        for col, rule in (numeric or {}).items():
            v = r.get(col)
            if _missing(v):
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                warnings.append(f"{col} '{v}' is not a number (cleared)")
                r[col] = None
                continue
            if "min" in rule and num < rule["min"]:
                warnings.append(f"{col} {v} below {rule['min']} (cleared)")
                r[col] = None
        r.setdefault("source_row", i + 1)
        r["errors"] = "; ".join(errors)
        r["warnings"] = "; ".join(warnings)
        out.append(r)
    return out


@tool("partition_rows", provides=("data validation",))
def partition_rows(ctx: ToolContext, table: Table, condition: str = "errors == ''") -> dict[str, Table]:
    """Split rows into valid (condition true) and invalid."""
    valid, invalid = [], []
    for r in table:
        (valid if evaluate(condition, r) else invalid).append(r)
    return {"valid": valid, "invalid": invalid}


@tool("export_tables", provides=("export", "reporting"))
def export_tables(ctx: ToolContext, tables: dict[str, Table], columns: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Write several tables to CSV files (``<name>.csv``), returning {name: path}."""
    return {name: export_table(ctx, rows, f"{name}.csv", (columns or {}).get(name)) for name, rows in tables.items()}


@tool("dedupe_rows", provides=("data validation",))
def dedupe_rows(ctx: ToolContext, table: Table, key: str) -> dict[str, Any]:
    """Remove rows whose key is a case/whitespace-insensitive duplicate of an earlier row."""
    seen, out, dropped = set(), [], []
    for r in table:
        k = re.sub(r"\s+", " ", str(r.get(key, "")).strip().lower())
        if k in seen:
            dropped.append(r.get(key))
            continue
        seen.add(k)
        out.append({**r, key: k})
    return {"rows": out, "removed": dropped}


# --- ranking & selection --------------------------------------------------------------------

@tool("rank_rows", provides=("ranking logic",))
def rank_rows(ctx: ToolContext, table: Table, score: str, params: dict[str, Any] | None = None,
              where: str | None = None, extra_columns: dict[str, str] | None = None) -> Table:
    """Score rows with an expression, optionally filter, sort best-first and add derived columns."""
    params = params or {}
    scored = []
    for r in table:
        env = {**params, **r}
        if where and not evaluate(where, env):
            continue
        scored.append({**r, "score": round(float(evaluate(score, env)), 3)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(scored, start=1):
        r["rank"] = i
        for name, expr in (extra_columns or {}).items():
            r[name] = evaluate(expr, {**params, **r})
    return scored


@tool("select_best", provides=("ranking logic",))
def select_best(ctx: ToolContext, ranked: Table, eligible_if: str, escalate_message: str,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pick the highest-ranked row that meets the eligibility rule, otherwise escalate."""
    params = params or {}
    for r in ranked:
        if evaluate(eligible_if, {**params, **r}):
            alternatives = [x for x in ranked if x is not r and evaluate(eligible_if, {**params, **x})][:2]
            return {"selected": r, "alternatives": alternatives}
    raise Escalate(escalate_message.format(**params), {"candidates_considered": ranked[:5]})


# --- classification ---------------------------------------------------------------------------

class _Label(BaseModel):
    label: str
    reason: str


@tool("classify_text", provides=("classifier",), uses_llm=True)
def classify_text(ctx: ToolContext, text: str, labels: dict[str, list[str]], default: str) -> dict[str, str]:
    """Classify free text into one of the given labels (LLM, else keyword rules)."""
    if ctx.llm is not None:
        try:
            res = llm_api.ask_structured(ctx.llm, _Label, "Classify the text into exactly one of the labels.",
                                         f"Labels with example cues: {labels}\nText: {text}")
            if res.label in labels:
                return {"label": res.label, "reason": res.reason, "method": "llm"}
        except Exception as exc:
            ctx.note(f"LLM classification unavailable ({type(exc).__name__}); used keyword rules")
    low = (text or "").lower()
    hits = {lab: [c for c in cues if c in low] for lab, cues in labels.items()}
    best = max(hits, key=lambda k: len(hits[k]))
    if not hits[best]:
        return {"label": default, "reason": "no keyword cue matched; using default", "method": "rules"}
    return {"label": best, "reason": f"matched cue(s): {', '.join(hits[best])}", "method": "rules"}


# --- lookups & planning -----------------------------------------------------------------------

@tool("lookup_rules", provides=("ranking logic",))
def lookup_rules(ctx: ToolContext, key: str, rules: dict[str, Any], default_key: str | None = None) -> Any:
    """Return the rule set configured for a key (e.g. channel mix for a campaign objective)."""
    if key in rules:
        return rules[key]
    if default_key and default_key in rules:
        ctx.note(f"no rules for '{key}'; used '{default_key}'")
        return rules[default_key]
    raise ToolError(f"no rules configured for {key!r}")


@tool("build_timeline", provides=("reporting",))
def build_timeline(ctx: ToolContext, start_date: str, end_date: str, milestones: list[dict[str, Any]]) -> Table:
    """Turn relative milestones (days before/after start or end) into a dated checklist."""
    try:
        anchors = {"start": date.fromisoformat(str(start_date)), "end": date.fromisoformat(str(end_date))}
    except ValueError as exc:
        raise NeedsInput(f"Dates must look like 2026-11-01 ({exc}). Please send the campaign dates again.") from exc
    rows = []
    for m in milestones:
        due = anchors[m.get("relative_to", "start")] + timedelta(days=int(m.get("offset_days", 0)))
        rows.append({"due": due.isoformat(), "task": m["task"], "owner": m.get("owner", "-"), "done": "[ ]"})
    return sorted(rows, key=lambda r: r["due"])
