"""SEO keyword intent classification and category/page mapping."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from .. import llm as llm_api
from .base import ToolContext, tool
from .data import Table

Intent = Literal["informational", "commercial", "transactional", "navigational"]


class _KwIntent(BaseModel):
    keyword: str
    intent: Intent


class _KwIntents(BaseModel):
    items: list[_KwIntent]


def _rule_intent(kw: str, cues: dict[str, list[str]], brand_terms: list[str], default: str) -> tuple[str, str]:
    low = f" {kw.lower()} "
    for intent in ("navigational", "transactional", "commercial", "informational"):
        terms = brand_terms if intent == "navigational" else []
        for cue in cues.get(intent, []) + terms:
            if re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", low):
                return intent, f"cue '{cue}'"
    return default, "no cue; default"


@tool("classify_intent", provides=("llm/classifier", "classifier"), uses_llm=True)
def classify_intent(ctx: ToolContext, table: Table, field: str, cues: dict[str, list[str]],
                    brand_terms: list[str], default: str = "commercial") -> Table:
    """Label each keyword informational / commercial / transactional / navigational."""
    llm_labels: dict[str, str] = {}
    if ctx.llm is not None:
        try:
            res = llm_api.ask_structured(
                ctx.llm, _KwIntents,
                "Classify each search keyword's intent as informational, commercial, transactional or navigational. "
                f"Brand/navigational terms: {brand_terms}.",
                llm_api.data("\n".join(r[field] for r in table), "keywords"))
            llm_labels = {i.keyword.lower().strip(): i.intent for i in res.items}
        except Exception as exc:
            ctx.note(f"LLM intent classification unavailable ({type(exc).__name__}); used cue rules")
    out = []
    for r in table:
        kw = r[field]
        if kw.lower().strip() in llm_labels:
            intent, why = llm_labels[kw.lower().strip()], "llm"
        else:
            intent, why = _rule_intent(kw, cues, brand_terms, default)
        out.append({**r, "intent": intent, "intent_basis": why})
    return out


@tool("map_categories", provides=("classifier",))
def map_categories(ctx: ToolContext, table: Table, field: str, categories: dict[str, dict[str, Any]],
                   page_by_intent: dict[str, str], fallback_category: str = "General") -> Table:
    """Map each keyword to a product category and a recommended target page."""
    out = []
    for r in table:
        words = set(re.findall(r"[a-z0-9]+", r[field].lower()))
        best, best_hits = fallback_category, 0
        for cat, spec in categories.items():
            hits = sum(1 for t in spec["terms"] if set(t.split()) <= words)
            if hits > best_hits:
                best, best_hits = cat, hits
        slug = categories.get(best, {}).get("slug", "")
        page = page_by_intent.get(r["intent"], "/").format(slug=slug, category=best)
        out.append({**r, "category": best, "target_page": page})
    return out
