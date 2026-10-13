"""Simulated external APIs (shipment carrier API) used where real APIs are unavailable.

Behaviour is driven by data/sample/shipments.json so failure modes can be demonstrated:
``"simulate": "flaky_once"`` fails the first call (the engine retries), ``"down"`` always fails.
"""
from __future__ import annotations

import json
from typing import Any

from .base import ToolContext, TransientToolError, resolve_path, tool

_CALLS: dict[str, int] = {}


def carrier_api(ctx: ToolContext, db_path: str, tracking_number: str) -> dict[str, Any]:
    """Pretend HTTP call: GET /carriers/track/{tracking_number}."""
    db = json.loads(resolve_path(ctx, db_path).read_text())
    rec = db.get(tracking_number)
    if rec is None:
        return {"status": "not_found"}
    key = f"{ctx.run_id}:{tracking_number}"
    _CALLS[key] = _CALLS.get(key, 0) + 1
    mode = rec.get("simulate")
    if mode == "down" or (mode == "flaky_once" and _CALLS[key] == 1):
        raise TransientToolError(f"{rec.get('carrier', 'carrier')} tracking API timed out")
    return {k: v for k, v in rec.items() if k != "simulate"}


@tool("shipment_lookup", provides=("shipment lookup",))
def shipment_lookup(ctx: ToolContext, orders: list[dict[str, Any]], db_path: str) -> list[dict[str, Any]]:
    """Fetch carrier tracking for each order that has a tracking number.

    A transient failure is raised (so the engine retries the step); if it still fails after
    the retries, the engine's ``on_error: degrade`` policy calls ``shipment_lookup_degraded``.
    """
    out = []
    for o in orders:
        tn = o.get("tracking_number")
        if not tn:
            out.append({"order_id": o["order_id"], "tracking": None, "note": "not shipped yet"})
            continue
        out.append({"order_id": o["order_id"], "tracking_number": tn, "tracking": carrier_api(ctx, db_path, tn)})
    return out


@tool("shipment_lookup_degraded", provides=("shipment lookup",))
def shipment_lookup_degraded(ctx: ToolContext, orders: list[dict[str, Any]], db_path: str) -> list[dict[str, Any]]:
    """Per-order tracking lookup that records failures instead of raising (fallback path)."""
    out = []
    for o in orders:
        tn = o.get("tracking_number")
        if not tn:
            out.append({"order_id": o["order_id"], "tracking": None, "note": "not shipped yet"})
            continue
        try:
            out.append({"order_id": o["order_id"], "tracking_number": tn, "tracking": carrier_api(ctx, db_path, tn)})
        except TransientToolError as exc:
            ctx.note(f"{o['order_id']}: live tracking unavailable ({exc}); showing order-system status only")
            out.append({"order_id": o["order_id"], "tracking_number": tn, "tracking": None,
                        "note": "carrier tracking temporarily unavailable"})
    return out


@tool("summarize_orders", provides=("reporting",))
def summarize_orders(ctx: ToolContext, orders: list[dict[str, Any]], shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine order and shipment data into one status line per order."""
    by_id = {s["order_id"]: s for s in shipments}
    out = []
    for o in orders:
        s = by_id.get(o["order_id"], {})
        t = s.get("tracking") or {}
        items = ", ".join(f"{i['qty']}x {i['name']}" for i in o.get("items", []))
        if t:
            ship = t.get("status", "unknown").replace("_", " ")
            detail = f"{ship}, last seen {t.get('last_location')} ({t.get('last_update')})"
            if t.get("estimated_delivery") and t.get("status") != "delivered":
                detail += f", ETA {t['estimated_delivery']}"
        else:
            detail = s.get("note", "no shipment information")
        out.append({
            "order_id": o["order_id"], "order_date": o.get("order_date"), "order_status": o.get("status"),
            "items": items, "carrier": o.get("carrier") or "-", "tracking_number": o.get("tracking_number") or "-",
            "shipment": detail,
        })
    return out
