"""Shared HTTP client: timeouts, auth header, and mapping of failures onto the engine's error types.

* timeouts, connection errors, 429 and 5xx -> ``TransientToolError`` (the engine retries)
* other 4xx -> ``ToolError`` (not retried)
* 404 -> ``None`` so callers can turn "not found" into a business outcome
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from ..tools.base import ToolError, TransientToolError


class HttpJsonClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        headers = {"Accept": "application/json", "User-Agent": "workflow-agent/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.base_url = base_url
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._client.get(path, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientToolError(f"{urlparse(self.base_url).netloc}: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientToolError(f"{urlparse(self.base_url).netloc} returned HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ToolError(f"{urlparse(self.base_url).netloc} rejected the request (HTTP {resp.status_code})")
        try:
            return resp.json()
        except ValueError as exc:
            raise ToolError(f"{urlparse(self.base_url).netloc} returned invalid JSON") from exc

    def close(self) -> None:
        self._client.close()
