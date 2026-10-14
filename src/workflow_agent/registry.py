"""Workflow registry: the Excel file is the source of truth, YAML binds steps to tools.

* ``Workflows`` sheet -> what each workflow is (name, trigger, inputs, steps, decision
  logic, tools, expected output). Steps are split on "→".
* ``Test_Questions`` sheet (optional) -> example requests used by the router.
* ``config/workflow_bindings.yaml`` -> for each Workflow_ID: input schema, one tool call per
  Excel step, and how to present the result.

Adding an 11th workflow = one Excel row + one YAML block (+ a new tool only if no
existing tool fits). ``validate()`` checks that the two stay in sync.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openpyxl import load_workbook

from .tools import TOOLS

REQUIRED_COLUMNS = ["Workflow_ID", "Workflow_Name", "Trigger", "Inputs", "Steps", "Decision_Logic",
                    "Tools_Required", "Expected_Output"]
STEP_SPLIT = re.compile(r"\s*(?:→|->|=>)\s*")


class RegistryError(ValueError):
    pass


@dataclass
class StepBinding:
    label: str  # from Excel
    tool: str
    args: dict[str, Any]
    save_as: str
    retries: int = 0
    on_error: str = "fail"  # fail | continue | degrade
    fallback_tool: str | None = None
    describe: str | None = None


@dataclass
class WorkflowSpec:
    id: str
    name: str
    trigger: str
    inputs_text: str
    steps_text: list[str]
    decision_logic: str
    tools_required: list[str]
    expected_output: str
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: list[StepBinding] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    executable: bool = False

    def card(self) -> str:
        """Short description used by the router (LLM prompt and keyword index)."""
        return (f"{self.id} {self.name}: triggered when {self.trigger.lower()}. "
                f"Output: {self.expected_output}. Examples: {'; '.join(self.examples)}")


@dataclass
class Registry:
    workflows: dict[str, WorkflowSpec]
    warnings: list[str]

    def executable(self) -> list[WorkflowSpec]:
        return [w for w in self.workflows.values() if w.executable]

    def get(self, wid: str) -> WorkflowSpec:
        return self.workflows[wid]


def _read_sheet(wb, name: str) -> list[dict[str, Any]]:
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    return [dict(zip(header, r, strict=False)) for r in rows[1:] if any(v not in (None, "") for v in r)]


def load_registry(excel_path: Path, bindings_path: Path) -> Registry:
    if not excel_path.exists():
        raise RegistryError(f"workflow Excel not found: {excel_path}")
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    sheet = "Workflows" if "Workflows" in wb.sheetnames else wb.sheetnames[0]
    rows = _read_sheet(wb, sheet)
    missing = [c for c in REQUIRED_COLUMNS if rows and c not in rows[0]]
    if missing:
        raise RegistryError(f"sheet {sheet!r} is missing columns: {missing}")
    examples: dict[str, list[str]] = {}
    if "Test_Questions" in wb.sheetnames:
        for r in _read_sheet(wb, "Test_Questions"):
            if r.get("Workflow_ID") and r.get("Test_Request"):
                examples.setdefault(str(r["Workflow_ID"]).strip(), []).append(str(r["Test_Request"]).strip())

    bindings = yaml.safe_load(bindings_path.read_text(encoding="utf-8")) if bindings_path.exists() else {}
    bindings = bindings or {}
    workflows: dict[str, WorkflowSpec] = {}
    warnings: list[str] = []
    for r in rows:
        wid = str(r["Workflow_ID"]).strip()
        spec = WorkflowSpec(
            id=wid, name=str(r["Workflow_Name"]).strip(), trigger=str(r["Trigger"] or ""),
            inputs_text=str(r["Inputs"] or ""), steps_text=[s for s in STEP_SPLIT.split(str(r["Steps"] or "")) if s],
            decision_logic=str(r["Decision_Logic"] or ""),
            tools_required=[t.strip() for t in re.split(r"[;,]", str(r["Tools_Required"] or "")) if t.strip()],
            expected_output=str(r["Expected_Output"] or ""), examples=examples.get(wid, []),
        )
        b = bindings.get(wid)
        if b is None:
            warnings.append(f"{wid} {spec.name}: no binding in {bindings_path.name}; it is listed but cannot run")
        else:
            try:
                _bind(spec, b)
                spec.executable = True
                warnings.extend(_coverage_warnings(spec))
            except RegistryError as exc:
                warnings.append(f"{wid} {spec.name}: {exc}")
        workflows[wid] = spec
    for wid in set(bindings) - set(workflows):
        warnings.append(f"binding {wid} has no matching row in the Excel file; ignored")
    return Registry(workflows, warnings)


def _bind(spec: WorkflowSpec, b: dict[str, Any]) -> None:
    spec.keywords = b.get("keywords", [])
    spec.examples += b.get("examples", [])
    spec.inputs = b.get("inputs", {}) or {}
    spec.report = b.get("report", {}) or {}
    raw_steps = b.get("steps", [])
    if len(raw_steps) != len(spec.steps_text):
        raise RegistryError(f"Excel lists {len(spec.steps_text)} steps but the binding has {len(raw_steps)}")
    steps = []
    for i, (label, s) in enumerate(zip(spec.steps_text, raw_steps, strict=True), start=1):
        tool_name = s.get("tool")
        if tool_name not in TOOLS:
            raise RegistryError(f"step {i} ({label}) uses unknown tool {tool_name!r}")
        params = TOOLS[tool_name].params
        bad = set(s.get("args", {})) - set(params)
        if bad:
            raise RegistryError(f"step {i} ({label}): tool {tool_name} has no parameter(s) {sorted(bad)}")
        required = [n for n, p in inspect.signature(TOOLS[tool_name].func).parameters.items()
                    if n != "ctx" and p.default is inspect.Parameter.empty]
        absent = [n for n in required if n not in s.get("args", {})]
        if absent:
            raise RegistryError(f"step {i} ({label}): missing required argument(s) {absent} for {tool_name}")
        fb = s.get("fallback_tool")
        if fb and fb not in TOOLS:
            raise RegistryError(f"step {i} ({label}): unknown fallback tool {fb!r}")
        steps.append(StepBinding(label=label, tool=tool_name, args=s.get("args", {}), save_as=s.get("save_as", f"step{i}"),
                                 retries=int(s.get("retries", 0)), on_error=s.get("on_error", "fail"),
                                 fallback_tool=fb, describe=s.get("describe")))
    spec.steps = steps


def _coverage_warnings(spec: WorkflowSpec) -> list[str]:
    """Warn when a capability named in the Excel 'Tools_Required' column is not provided by any bound tool."""
    provided = {p for s in spec.steps for p in TOOLS[s.tool].provides}
    provided |= {p for s in spec.steps if s.fallback_tool for p in TOOLS[s.fallback_tool].provides}
    out = []
    for need in spec.tools_required:
        n = need.lower()
        if not any(n == p or n in p or p in n for p in provided):
            out.append(f"{spec.id}: Excel requires tool '{need}' but no bound tool declares it")
    return out
