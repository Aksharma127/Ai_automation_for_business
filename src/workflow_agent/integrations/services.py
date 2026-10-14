"""Order and carrier services: file-backed simulations (default) and HTTP implementations.

HTTP contract (adapt the small mapping functions below to your real API):

    GET {ORDERS_API_URL}/orders?order_id=ORD-1001        -> [order, ...]  (or {"orders": [...]})
    GET {ORDERS_API_URL}/orders?customer_email=a@b.com   -> [order, ...]
    GET {CARRIER_API_URL}/track/{tracking_number}        -> {"status", "last_location", "last_update", "estimated_delivery"}

An order is ``{"order_id", "customer_email", "status", "order_date", "items": [{"sku", "name", "qty"}],
"tracking_number", "carrier"}``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..tools.base import TransientToolError
from .http import HttpJsonClient


class OrderService(Protocol):
    def find_orders(self, field: str, value: str) -> list[dict[str, Any]]: ...


class CarrierService(Protocol):
    def track(self, tracking_number: str, *, attempt_key: str) -> dict[str, Any]: ...


# --- simulated (file-backed) ------------------------------------------------------------------

class FileOrderService:
    def __init__(self, path: Path):
        self.path = path

    def find_orders(self, field: str, value: str) -> list[dict[str, Any]]:
        orders = json.loads(self.path.read_text(encoding="utf-8"))
        return [o for o in orders if str(o.get(field, "")).strip().lower() == str(value).strip().lower()]


class FileCarrierService:
    """Behaviour comes from the JSON file: ``"simulate": "flaky_once"`` fails the first call per
    run, ``"down"`` always fails, so retries and degradation can be demonstrated."""

    def __init__(self, path: Path):
        self.path = path
        self._calls: dict[str, int] = {}

    def track(self, tracking_number: str, *, attempt_key: str) -> dict[str, Any]:
        db = json.loads(self.path.read_text(encoding="utf-8"))
        rec = db.get(tracking_number)
        if rec is None:
            return {"status": "not_found"}
        key = f"{attempt_key}:{tracking_number}"
        self._calls[key] = self._calls.get(key, 0) + 1
        mode = rec.get("simulate")
        if mode == "down" or (mode == "flaky_once" and self._calls[key] == 1):
            raise TransientToolError(f"{rec.get('carrier', 'carrier')} tracking API timed out")
        return {k: v for k, v in rec.items() if k != "simulate"}


# --- HTTP -------------------------------------------------------------------------------------

class HttpOrderService:
    def __init__(self, client: HttpJsonClient):
        self.client = client

    def find_orders(self, field: str, value: str) -> list[dict[str, Any]]:
        data = self.client.get("/orders", params={field: value})
        if data is None:
            return []
        orders = data.get("orders", []) if isinstance(data, dict) else data
        return [_order_from_api(o) for o in orders]


class HttpCarrierService:
    def __init__(self, client: HttpJsonClient):
        self.client = client

    def track(self, tracking_number: str, *, attempt_key: str) -> dict[str, Any]:
        data = self.client.get(f"/track/{tracking_number}")
        return {"status": "not_found"} if data is None else _tracking_from_api(data)


def _order_from_api(o: dict[str, Any]) -> dict[str, Any]:
    """Map the remote order shape onto the internal one (adjust field names for your API)."""
    return {
        "order_id": o.get("order_id") or o.get("id"),
        "customer_email": o.get("customer_email") or o.get("email"),
        "status": o.get("status"),
        "order_date": o.get("order_date") or o.get("created_at"),
        "items": [{"sku": i.get("sku"), "name": i.get("name") or i.get("title"), "qty": i.get("qty") or i.get("quantity", 1)}
                  for i in o.get("items", [])],
        "tracking_number": o.get("tracking_number"),
        "carrier": o.get("carrier"),
    }


def _tracking_from_api(t: dict[str, Any]) -> dict[str, Any]:
    return {k: t.get(k) for k in ("carrier", "status", "last_location", "last_update", "estimated_delivery")}


@dataclass
class Services:
    orders: OrderService
    carrier: CarrierService


def build_services(settings: Any, root: Path, transport: httpx.BaseTransport | None = None) -> Services:
    """Pick real HTTP integrations when their URL is configured, simulations otherwise."""
    if settings.orders_api_url:
        orders: OrderService = HttpOrderService(HttpJsonClient(settings.orders_api_url, settings.orders_api_token,
                                                               settings.http_timeout_sec, transport))
    else:
        orders = FileOrderService(root / "data" / "sample" / "orders.json")
    if settings.carrier_api_url:
        carrier: CarrierService = HttpCarrierService(HttpJsonClient(settings.carrier_api_url, settings.carrier_api_token,
                                                                    settings.http_timeout_sec, transport))
    else:
        carrier = FileCarrierService(root / "data" / "sample" / "shipments.json")
    return Services(orders=orders, carrier=carrier)
