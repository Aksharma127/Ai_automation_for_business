"""Extract a workflow's declared inputs from the user's request.

The input schema lives in the YAML binding (type, description, default, optional regex
``pattern`` and value ``aliases``). With an LLM, a Pydantic model is built from that schema
at runtime and filled via structured output (tool calling); offline, the regex patterns are
used. Either way, defaults fill the gaps and values are type-checked.
"""
from __future__ import annotations

import re
from typing import Any, cast

from pydantic import Field, create_model

from . import llm as llm_api
from .registry import WorkflowSpec

PY_TYPES = {"string": str, "number": float, "integer": int, "boolean": bool, "list": list[str]}


def _cast(value: Any, typ: str) -> Any:
    if value is None or value == "":
        return None
    if typ == "number":
        num = float(str(value).replace(",", ""))
        return int(num) if num.is_integer() else num
    if typ == "integer":
        return int(float(str(value).replace(",", "")))
    if typ == "boolean":
        return str(value).lower() in {"1", "true", "yes", "y"}
    if typ == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in re.split(r",|;|\band\b", str(value)) if v.strip()]
    return str(value).strip()


def _regex_extract(request: str, spec: dict[str, Any]) -> Any:
    for pat in ([spec["pattern"]] if isinstance(spec.get("pattern"), str) else spec.get("pattern", [])):
        m = re.search(pat, request, flags=re.I)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return None


def _apply_aliases(value: Any, spec: dict[str, Any]) -> Any:
    aliases = spec.get("aliases")
    if not aliases or value is None:
        return value
    low = str(value).lower()
    for canon, words in aliases.items():
        if low == canon or low in [w.lower() for w in words]:
            return canon
    return value


def extract_inputs(workflow: WorkflowSpec, request: str, llm: Any | None, notes: list[str],
                   fill_defaults: bool = True) -> dict[str, Any]:
    """Inputs stated in the request; with ``fill_defaults`` every declared input is present."""
    specs = {k: v for k, v in workflow.inputs.items() if v.get("extract", True)}
    found: dict[str, Any] = {}
    if llm is not None and specs:
        fields = {name: (PY_TYPES.get(s.get("type", "string"), str) | None,
                         Field(default=None, description=s.get("description", name)))
                  for name, s in specs.items()}
        Model = create_model(f"{workflow.id}_Inputs", **cast(dict[str, Any], fields))
        try:
            res = llm_api.structured(llm, Model).invoke([
                ("system", "Extract the workflow inputs that are explicitly stated in the user's request. "
                           "Leave a field null if the request does not state it. Never guess.\n"
                           + llm_api.UNTRUSTED_RULE),
                ("human", f"Workflow: {workflow.name}\nRequest:\n{llm_api.data(request, 'request')}")])
            found = {k: v for k, v in res.model_dump().items() if v not in (None, "", [])}
        except Exception as exc:
            notes.append(f"LLM input extraction failed ({type(exc).__name__}); used patterns")
    for name, s in specs.items():
        if name not in found and s.get("pattern"):
            v = _regex_extract(request, s)
            if v is not None:
                found[name] = v
    values: dict[str, Any] = {}
    for name, s in workflow.inputs.items():
        v = found.get(name)
        try:
            v = _cast(_apply_aliases(v, s), s.get("type", "string"))
        except (TypeError, ValueError):
            notes.append(f"could not read {name}={v!r}; using default")
            v = None
        if v is not None:
            values[name] = v
        elif fill_defaults:
            values[name] = s.get("default")
    return values
