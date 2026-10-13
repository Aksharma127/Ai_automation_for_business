"""Duplicate product detection: normalisation, exact-key matching and fuzzy attribute similarity."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any

from .base import ToolContext, tool
from .data import Table

_SYNONYMS = {"gray": "grey", "tshirt": "t shirt", "tee": "t shirt", "mens": "men", "shoes": "shoe"}


def normalize_text(value: Any) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower().replace("'", ""))
    s = re.sub(r"\bsize\b", " ", s)
    return " ".join(_SYNONYMS.get(w, w) for w in s.split())


@tool("normalize_fields", provides=("text similarity",))
def normalize_fields(ctx: ToolContext, table: Table, fields: list[str]) -> Table:
    """Add ``<field>_norm`` columns: lower-cased, punctuation-free, synonym-folded text."""
    return [{**r, **{f"{f}_norm": normalize_text(r.get(f)) for f in fields}} for r in table]


@tool("find_exact_duplicates", provides=("csv/database reader",))
def find_exact_duplicates(ctx: ToolContext, table: Table, key: str) -> list[dict[str, Any]]:
    """Group rows that share the same normalised identifier."""
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(table):
        if r.get(key):
            groups.setdefault(r[key], []).append(i)
    return [{"rows": idx, "match": f"identical {key.replace('_norm', '')}", "similarity": 1.0}
            for k, idx in groups.items() if len(idx) > 1]


@tool("similar_pairs", provides=("text similarity",))
def similar_pairs(ctx: ToolContext, table: Table, text_field: str, attributes: list[str],
                  min_similarity: float = 0.75) -> list[dict[str, Any]]:
    """Compare every pair of rows on name similarity plus matching attributes."""
    pairs = []
    for i, j in combinations(range(len(table)), 2):
        a, b = table[i], table[j]
        ta, tb = a.get(text_field, ""), b.get(text_field, "")
        seq = SequenceMatcher(None, ta, tb).ratio()
        sa, sb = set(ta.split()), set(tb.split())
        jac = len(sa & sb) / len(sa | sb) if sa | sb else 0
        name_sim = max(seq, jac)
        same = [f for f in attributes if normalize_text(a.get(f)) and normalize_text(a.get(f)) == normalize_text(b.get(f))]
        attr_sim = len(same) / len(attributes) if attributes else 0
        score = round(0.6 * name_sim + 0.4 * attr_sim, 3)
        if score >= min_similarity:
            pairs.append({"rows": [i, j], "similarity": score,
                          "match": f"name similarity {name_sim:.2f}; same {', '.join(same) or 'no attributes'}"})
    return pairs


@tool("group_duplicates", provides=("text similarity",))
def group_duplicates(ctx: ToolContext, table: Table, exact: list[dict], similar: list[dict]) -> list[dict[str, Any]]:
    """Merge exact and fuzzy matches into connected groups (union-find)."""
    parent = list(range(len(table)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in exact + similar:
        first = m["rows"][0]
        for other in m["rows"][1:]:
            parent[find(other)] = find(first)
    clusters: dict[int, list[int]] = {}
    for i in range(len(table)):
        clusters.setdefault(find(i), []).append(i)
    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        ms = set(members)
        evidence = [m for m in exact + similar if set(m["rows"]) <= ms]
        groups.append({"members": members, "evidence": evidence,
                       "has_exact": any(m["similarity"] == 1.0 and m["match"].startswith("identical") for m in evidence)})
    return groups


@tool("assign_confidence", provides=("text similarity",))
def assign_confidence(ctx: ToolContext, table: Table, groups: list[dict], high_threshold: float = 0.85,
                      show: list[str] | None = None) -> list[dict[str, Any]]:
    """Exact identifier match = definite duplicate; otherwise possible (high/medium) by similarity.

    In a group that mixes both, members linked only by similarity are marked "(possible)".
    """
    show = show or ["sku", "product_name"]
    out = []
    for g in groups:
        exact_rows = {i for e in g["evidence"] if e["match"].startswith("identical") for i in e["rows"]}
        fuzzy = [e["similarity"] for e in g["evidence"] if not e["match"].startswith("identical")]
        best = max(fuzzy) if fuzzy else 1.0
        if exact_rows:
            conf = "Definite duplicate"
        elif best >= high_threshold:
            conf = "Possible duplicate (high)"
        else:
            conf = "Possible duplicate (medium)"

        def label(i: int) -> str:
            txt = " / ".join(str(table[i].get(f, "")).strip() for f in show)
            return txt + (" (possible)" if exact_rows and i not in exact_rows else "")

        out.append({
            "confidence": conf, "score": 1.0 if exact_rows else best,
            "products": " | ".join(label(i) for i in g["members"]),
            "matching_fields": "; ".join(dict.fromkeys(e["match"] for e in sorted(g["evidence"], key=lambda e: -e["similarity"]))),
        })
    order = {"Definite duplicate": 0, "Possible duplicate (high)": 1, "Possible duplicate (medium)": 2}
    out.sort(key=lambda r: (order[r["confidence"]], -r["score"]))
    return [{"group": n, **r} for n, r in enumerate(out, start=1)]
