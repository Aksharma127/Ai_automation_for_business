"""Order and shipment tools. They talk to ``ctx.services`` (see ``integrations/``), which is a
real HTTP API when ``ORDERS_API_URL`` / ``CARRIER_API_URL`` are set and the file-backed
simulation in ``data/sample`` otherwise."""
from __future__ import annotations

from typing import Any

from .base import NeedsInput, ToolContext, ToolError, TransientToolError, tool


def _services(ctx: ToolContext) -> Any:
    if ctx.services is None:
        raise ToolError("order/carrier services are not configured")
    return ctx.services


@tool("lookup_orders", provides=("order database/api",))
def lookup_orders(ctx: ToolContext, field: str, value: str, if_none: str) -> list[dict[str, Any]]:
    """Find orders by order_id or customer_email in the order system; ask for another identifier if none."""
    if field not in {"order_id", "customer_email"}:
        raise ToolError(f"orders can't be searched by {field!r}")
    orders = _services(ctx).orders.find_orders(field, value)
    if not orders:
        raise NeedsInput(if_none.format(value=value), [field])
    return orders


def _track_all(ctx: ToolContext, orders: list[dict[str, Any]], tolerate_failures: bool) -> list[dict[str, Any]]:
    carrier = _services(ctx).carrier
    out = []
    for o in orders:
        tn = o.get("tracking_number")
        if not tn:
            out.append({"order_id": o["order_id"], "tracking": None, "note": "not shipped yet"})
            continue
        try:
            out.append({"order_id": o["order_id"], "tracking_number": tn,
                        "tracking": carrier.track(tn, attempt_key=ctx.run_id)})
        except TransientToolError as exc:
            if not tolerate_failures:
                raise
            ctx.note(f"{o['order_id']}: live tracking unavailable ({exc}); showing order-system status only")
            out.append({"order_id": o["order_id"], "tracking_number": tn, "tracking": None,
                        "note": "carrier tracking temporarily unavailable"})
    return out


@tool("shipment_lookup", provides=("shipment lookup",))
def shipment_lookup(ctx: ToolContext, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch carrier tracking for each shipped order (raises on carrier failure so the engine retries)."""
    return _track_all(ctx, orders, tolerate_failures=False)


@tool("shipment_lookup_degraded", provides=("shipment lookup",))
def shipment_lookup_degraded(ctx: ToolContext, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-order tracking lookup that records carrier failures instead of raising (fallback path)."""
    return _track_all(ctx, orders, tolerate_failures=True)


@tool("summarize_orders", provides=("reporting",))
def summarize_orders(ctx: ToolContext, orders: list[dict[str, Any]], shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine order and shipment data into one status line per order."""
    by_id = {s["order_id"]: s for s in shipments}
    out = []
    for o in orders:
        s = by_id.get(o["order_id"], {})
        t = s.get("tracking") or {}
        items = ", ".join(f"{i.get('qty', 1)}x {i.get('name')}" for i in o.get("items", []))
        if t and t.get("status") != "not_found":
            ship = str(t.get("status") or "unknown").replace("_", " ")
            detail = f"{ship}, last seen {t.get('last_location')} ({t.get('last_update')})"
            if t.get("estimated_delivery") and t.get("status") != "delivered":
                detail += f", ETA {t['estimated_delivery']}"
        elif t:
            detail = "carrier has no record of this tracking number yet"
        else:
            detail = s.get("note", "no shipment information")
        out.append({
            "order_id": o["order_id"], "order_date": o.get("order_date"), "order_status": o.get("status"),
            "items": items, "carrier": o.get("carrier") or "-", "tracking_number": o.get("tracking_number") or "-",
            "shipment": detail,
        })
    return out
