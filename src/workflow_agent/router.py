"""Workflow selection.

Two strategies behind one interface:

* ``KeywordRouter`` - offline, deterministic. Weighted token overlap (IDF-weighted) between
  the request and each workflow's name, trigger, keywords, example requests and expected
  output - all read from the Excel file and bindings, so a new workflow is routable with no
  code change.
* ``LLMRouter`` - the LLM is given every workflow card and must call the
  ``select_workflow`` tool (structured tool call) with an id, a confidence and its reasoning.
  The keyword scores are passed in as hints. Falls back to the keyword router on any error.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from . import llm as llm_api
from .registry import WorkflowSpec

STOP = set("""a an the and or of to for in on at by with this that these those is are be it its my our your
me we i you can could would should please which what where who how do does show give find list all any
from into as about today now new get""".split())


def tokenize(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        for suf in ("ing", "ies", "es", "ed", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(w)
    return out


@dataclass
class RouteDecision:
    workflow_id: str | None
    confidence: float
    reasoning: str
    method: str
    candidates: list[dict[str, Any]] = field(default_factory=list)


class KeywordRouter:
    SATURATION = 6.0  # evidence at which confidence reaches ~63% (before the margin discount)
    FIELD_WEIGHTS = {"name": 3.0, "keywords": 3.0, "examples": 2.0, "trigger": 2.0, "output": 1.0, "steps": 0.5}

    def __init__(self, workflows: list[WorkflowSpec]):
        self.workflows = workflows
        self.index: dict[str, dict[str, float]] = {}
        for w in workflows:
            fields = {"name": w.name, "keywords": " ".join(w.keywords), "examples": " ".join(w.examples),
                      "trigger": w.trigger, "output": w.expected_output, "steps": " ".join(w.steps_text)}
            weights: dict[str, float] = {}
            for fname, text in fields.items():
                for t in tokenize(text):
                    weights[t] = max(weights.get(t, 0), self.FIELD_WEIGHTS[fname])
            self.index[w.id] = weights
        n = len(workflows)
        df: dict[str, int] = {}
        for weights in self.index.values():
            for t in weights:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}

    def scores(self, request: str) -> list[dict[str, Any]]:
        """Evidence per workflow = sum of IDF x field-weight over request terms it contains.

        Not normalised by request length, so long requests full of values (names, dates)
        are not penalised for the extra words.
        """
        q = list(dict.fromkeys(tokenize(request)))
        out = []
        for w in self.workflows:
            idx = self.index[w.id]
            hits = [t for t in q if t in idx]
            s = sum(self.idf[t] * idx[t] for t in hits)
            out.append({"workflow_id": w.id, "name": w.name, "score": round(s, 2), "matched": hits})
        return sorted(out, key=lambda r: r["score"], reverse=True)

    def route(self, request: str, min_confidence: float) -> RouteDecision:
        ranked = self.scores(request)
        if not ranked or ranked[0]["score"] == 0:
            return RouteDecision(None, 0.0, "no workflow vocabulary found in the request", "keyword", ranked[:3])
        top = ranked[0]
        second = ranked[1]["score"] if len(ranked) > 1 else 0.0
        strength = 1 - math.exp(-top["score"] / self.SATURATION)  # how much evidence
        margin = (top["score"] - second) / top["score"]            # how clearly it beats the runner-up
        conf = round(strength * (0.5 + 0.5 * margin), 3)
        reasoning = f"matched terms {top['matched']} (evidence {top['score']}, runner-up {second})"
        if conf < min_confidence:
            return RouteDecision(None, conf, f"best guess {top['workflow_id']} is too uncertain: {reasoning}",
                                 "keyword", ranked[:3])
        return RouteDecision(top["workflow_id"], conf, reasoning, "keyword", ranked[:3])


class SelectWorkflow(BaseModel):
    """Select the business workflow that should handle the user's request."""

    workflow_id: str = Field(description="One of the listed workflow ids, or NONE if no workflow fits")
    confidence: float = Field(ge=0, le=1, description="How sure you are, 0-1")
    reasoning: str = Field(description="One or two sentences on why this workflow fits")


class LLMRouter:
    def __init__(self, workflows: list[WorkflowSpec], llm: Any):
        self.workflows = {w.id: w for w in workflows}
        self.llm = llm
        self.fallback = KeywordRouter(workflows)

    def route(self, request: str, min_confidence: float) -> RouteDecision:
        hints = self.fallback.scores(request)[:3]
        catalog = "\n".join(f"- {w.card()}" for w in self.workflows.values())
        system = ("You are the routing step of a business automation agent. Read the user's request and call "
                  "select_workflow with the single workflow that should handle it. Use NONE if nothing fits.")
        user = (f"Workflows:\n{catalog}\n\nKeyword-match hints (may be wrong): "
                f"{[(h['workflow_id'], h['score']) for h in hints]}\n\nUser request: {request}")
        try:
            # SelectWorkflow is bound as a schema the model must fill (tool calling, or native
            # structured output on providers that don't allow forcing a tool)
            choice: SelectWorkflow = llm_api.structured(self.llm, SelectWorkflow).invoke(
                [("system", system), ("human", user)])
        except Exception as exc:
            d = self.fallback.route(request, min_confidence)
            d.reasoning = f"LLM routing failed ({type(exc).__name__}); keyword fallback: {d.reasoning}"
            return d
        wid = choice.workflow_id.strip().upper()
        if wid not in self.workflows or choice.confidence < min_confidence:
            return RouteDecision(None, choice.confidence, choice.reasoning, "llm-tool-call", hints)
        return RouteDecision(wid, round(choice.confidence, 3), choice.reasoning, "llm-tool-call", hints)


def make_router(workflows: list[WorkflowSpec], llm: Any | None):
    return LLMRouter(workflows, llm) if llm is not None else KeywordRouter(workflows)
