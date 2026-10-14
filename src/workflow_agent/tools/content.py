"""Content generation (LLM with a deterministic template fallback) and text validation."""
from __future__ import annotations

import re
from typing import Any

from .. import llm as llm_api
from .base import ToolContext, tool

GROUNDING_RULES = (
    "Use ONLY the facts provided. Never invent product attributes, numbers, materials, "
    "prices, dates or claims that are not in the facts. If a fact is listed as missing, "
    "do not mention or guess it. Return only the requested text, no preamble."
)


def _fmt(v: Any) -> str:
    if isinstance(v, list):
        items = [str(x) for x in v if x not in (None, "")]
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return "" if v is None else str(v)


def render_template(template: str, facts: dict[str, Any]) -> str:
    """Format ``{field}`` placeholders; ``[[...]]`` segments vanish if any field inside is missing.

    ``{field|lower}`` lower-cases a value.
    """
    flat = {k: _fmt(v) for k, v in facts.items()}

    def sub(text: str, strict: bool = True) -> str | None:
        missing = False

        def repl(m: re.Match) -> str:
            nonlocal missing
            name, _, flt = m.group(1).partition("|")
            val = flat.get(name, "")
            if not val:
                missing = True
            return val.lower() if flt == "lower" else val

        out = re.sub(r"\{([a-zA-Z0-9_.|]+)\}", repl, text)
        return None if missing and strict else out

    def seg(m: re.Match) -> str:
        return sub(m.group(1)) or ""

    text = re.sub(r"\[\[(.*?)\]\]", seg, template, flags=re.S)
    text = (sub(text, strict=False) or "") if "{" in text else text
    return re.sub(r"[ \t]+", " ", text or "").replace(" .", ".").strip()


def trim(text: str, max_chars: int | None) -> str:
    if not max_chars or len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + "…"


@tool("generate_content", provides=("llm", "text validation"), uses_llm=True)
def generate_content(ctx: ToolContext, kind: str, facts: dict[str, Any], template: str,
                     instructions: str = "", missing: list[str] | None = None, max_chars: int | None = None,
                     guard_terms: dict[str, list[str]] | None = None) -> str:
    """Write a piece of content from facts only; validates length and blocks invented attributes."""
    missing = missing or []
    text = None
    if ctx.llm is not None:
        try:
            prompt = (f"Task: write the {kind.replace('_', ' ')}.\n{instructions}\n"
                      f"{'Maximum length: ' + str(max_chars) + ' characters.' if max_chars else ''}\n"
                      f"Facts:\n{llm_api.data({k: v for k, v in facts.items() if v not in (None, '', [])}, 'facts')}\n"
                      f"Missing (do not mention or guess): {missing or 'none'}")
            text = llm_api.ask_text(ctx.llm, GROUNDING_RULES, prompt).strip().strip('"')
            violation = _invented(text, facts, missing, guard_terms or {})
            if violation:
                ctx.note(f"{kind}: LLM output mentioned unsupported {violation}; replaced with template text")
                text = None
        except Exception as exc:
            ctx.note(f"{kind}: LLM unavailable ({type(exc).__name__}); used template")
            text = None
    if text is None:
        text = render_template(template, facts)
    if max_chars and len(text) > max_chars:
        text = trim(text, max_chars)
    return text


def _invented(text: str, facts: dict[str, Any], missing: list[str], guard_terms: dict[str, list[str]]) -> str | None:
    """Return the field name if the text names a value for a field that is missing from the facts."""
    low = text.lower()
    known = " ".join(_fmt(v).lower() for v in facts.values())
    for field_name, terms in guard_terms.items():
        if field_name in missing:
            for t in terms:
                if re.search(rf"\b{re.escape(t)}\b", low) and t not in known:
                    return f"{field_name} ('{t}')"
    return None
