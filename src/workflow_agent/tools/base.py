"""Tool registry and the small exception vocabulary the engine understands.

A tool is a plain Python function registered with ``@tool``. Workflows never import
tools directly: the YAML bindings refer to them by name, so a new workflow can reuse
any existing tool without code changes.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class WorkflowHalt(Exception):
    """Stops the workflow on purpose with a business outcome (not a crash).

    status: ``needs_input`` (ask the user for something), ``escalated`` (hand to a human)
    or ``no_result``.
    """

    def __init__(self, status: str, message: str, data: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.data = data


class NeedsInput(WorkflowHalt):
    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__("needs_input", message, {"missing": missing or []})


class Escalate(WorkflowHalt):
    def __init__(self, message: str, data: Any = None):
        super().__init__("escalated", message, data)


class TransientToolError(Exception):
    """A failure worth retrying (timeouts, rate limits, flaky simulated APIs)."""


class ToolError(Exception):
    """A non-retryable tool failure (bad input file, missing column, ...)."""


@dataclass
class ToolContext:
    """What every tool receives besides its arguments."""

    llm: Any = None  # a LangChain chat model, or None in offline mode
    root: Path = Path(".")
    output_dir: Path = Path("outputs")
    run_id: str = "local"
    notes: list[str] = field(default_factory=list)  # warnings surfaced in the final result

    def note(self, message: str) -> None:
        self.notes.append(message)


@dataclass
class ToolSpec:
    name: str
    func: Callable[..., Any]
    description: str
    provides: tuple[str, ...]  # capability labels matched against the Excel "Tools_Required" column
    uses_llm: bool

    @property
    def params(self) -> list[str]:
        return [p for p in inspect.signature(self.func).parameters if p != "ctx"]


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, *, provides: tuple[str, ...] = (), uses_llm: bool = False):
    """Register a function as a workflow tool."""

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in TOOLS:
            raise ValueError(f"tool {name!r} registered twice")
        doc = inspect.getdoc(func) or ""
        TOOLS[name] = ToolSpec(name, func, doc.splitlines()[0] if doc else name, provides, uses_llm)
        return func

    return deco


def call_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> Any:
    spec = TOOLS[name]
    unknown = set(args) - set(spec.params)
    if unknown:
        raise ToolError(f"tool {name!r} got unexpected argument(s): {sorted(unknown)}")
    return spec.func(ctx=ctx, **args)


def resolve_path(ctx: ToolContext, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ctx.root / p
