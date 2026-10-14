"""HTTP API (FastAPI).

    uvicorn --factory workflow_agent.api:create_app --host 0.0.0.0 --port 8000

Endpoints (all under /v1 need an API key: ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``):

    GET  /healthz                      liveness
    GET  /readyz                       readiness (registry loaded, database reachable)
    GET  /v1/workflows                 workflows loaded from the Excel file
    POST /v1/runs                      {"request": "..."}  -> run result (may be awaiting a reply)
    POST /v1/runs/upload               multipart: request=<text>, file=<csv|xlsx|json>
    POST /v1/runs/{run_id}/reply       {"answer": "..."}   -> continues a paused run
    GET  /v1/runs/{run_id}             stored run with its steps
    GET  /v1/runs                      recent runs (?limit=&status=)
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
import uuid
import zipfile
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from .engine import RunNotFound, WorkflowAgent
from .observability import configure_logging, log
from .render import render_run
from .settings import Settings, get_settings

ALLOWED_UPLOAD_TYPES = {".csv", ".xlsx", ".json"}
MAX_XLSX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_XLSX_ENTRIES = 2000


# --- schemas ----------------------------------------------------------------------------------

class RunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=10_000, examples=["Which products need restocking?"])


class ReplyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10_000, examples=["The order ID is ORD-1001"])


class RunResponse(BaseModel):
    run_id: str
    status: str
    awaiting_reply: bool
    question: str | None = None
    workflow: dict[str, Any] | None = None
    inputs: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    answer: str | None = None
    notes: list[str] = []
    usage: dict[str, Any] = {}
    duration_ms: float = 0.0
    markdown: str = ""


def to_response(state: dict[str, Any]) -> RunResponse:
    route = state.get("route") or {}
    wf = None
    if state.get("workflow_id") or route:
        wf = {"id": state.get("workflow_id"), "name": state.get("workflow_name"),
              "confidence": route.get("confidence"), "method": route.get("method"), "reasoning": route.get("reasoning")}
    return RunResponse(
        run_id=state["run_id"], status=state.get("status", "unknown"), awaiting_reply=state.get("awaiting_reply", False),
        question=state.get("message") if state.get("awaiting_reply") else None, workflow=wf,
        inputs={k: v for k, v in (state.get("inputs") or {}).items() if k != "request"},
        steps=state.get("trace") or [], result=state.get("result"), answer=state.get("answer"),
        notes=list(dict.fromkeys(state.get("notes") or [])), usage=state.get("usage") or {},
        duration_ms=state.get("duration_ms", 0.0), markdown=render_run(state),
    )


# --- auth & rate limiting -----------------------------------------------------------------------

class RateLimiter:
    """Sliding-window limit per API key. In-process: put a shared limiter (gateway/Redis) in
    front when running several replicas."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """None if allowed, else seconds until the next request is allowed."""
        if self.per_minute <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return 60 - (now - q[0])
            q.append(now)
        return None


# Declared for the OpenAPI schema only, so /docs shows an "Authorize" button; _extract_key does the check.
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _principal_for(key: str) -> str:
    return "key-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def _extract_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    return key or None


# --- uploads ------------------------------------------------------------------------------------

def save_upload(upload: UploadFile, settings: Settings) -> Path:
    """Validate and store an uploaded data file under UPLOAD_DIR with a random name."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(415, f"unsupported file type {suffix or '(none)'}; use .csv, .xlsx or .json")
    limit = int(settings.max_upload_mb * 1024 * 1024)
    data = bytearray()
    while chunk := upload.file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"file is larger than {settings.max_upload_mb:g} MB")
    if not data:
        raise HTTPException(422, "uploaded file is empty")
    if suffix == ".xlsx":
        _check_xlsx(bytes(data))
    else:
        try:
            bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "CSV/JSON uploads must be UTF-8 text") from exc
    dest_dir = settings.upload_dir / uuid.uuid4().hex
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"upload{suffix}"
    dest.write_bytes(bytes(data))
    return dest


def _check_xlsx(data: bytes) -> None:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_XLSX_ENTRIES or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
                raise HTTPException(413, "spreadsheet expands to more data than allowed")
            if "[Content_Types].xml" not in zf.namelist():
                raise HTTPException(422, "not a valid .xlsx file")
    except zipfile.BadZipFile as exc:
        raise HTTPException(422, "not a valid .xlsx file") from exc


# --- app ----------------------------------------------------------------------------------------

def create_app(settings: Settings | None = None, agent: WorkflowAgent | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    problems = settings.validate()
    if problems:
        raise RuntimeError("invalid production configuration: " + "; ".join(problems))
    if not settings.api_keys and not settings.auth_disabled:
        log.warning("no API_KEYS configured: /v1 endpoints are open (development only)")
    limiter = RateLimiter(settings.rate_limit_per_minute)
    state: dict[str, Any] = {"agent": agent}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = state["agent"] is None
        if owned:
            state["agent"] = WorkflowAgent(settings=settings)
        log.info("agent ready", extra={"workflows": len(state["agent"].registry.executable()),
                                       "mode": "llm" if state["agent"].llm else "offline"})
        yield
        if owned:  # an injected agent belongs to the caller
            state["agent"].close()

    app = FastAPI(title="Workflow Agent API", version="2.0.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                           allow_headers=["*"])

    def get_agent() -> WorkflowAgent:
        if state["agent"] is None:
            raise HTTPException(503, "agent is starting")
        agent_: WorkflowAgent = state["agent"]
        return agent_

    def principal(request: Request, _key: str | None = Security(API_KEY_HEADER)) -> str | None:
        key = _extract_key(request)
        if settings.api_keys and not settings.auth_disabled and (
                not key or not any(hmac.compare_digest(key, k) for k in settings.api_keys)):
            raise HTTPException(401, "missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})
        who = _principal_for(key) if key else None
        wait = limiter.check(who or (request.client.host if request.client else "anonymous"))
        if wait is not None:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(wait) + 1)})
        return who

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": rid, "path": request.url.path})
            response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
        response.headers["X-Request-ID"] = rid
        log.info("http", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                "status": response.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(agent_: WorkflowAgent = Depends(get_agent)) -> dict[str, Any]:
        try:
            agent_.store.ping()
        except Exception as exc:
            raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from exc
        return {"status": "ready", "workflows": len(agent_.registry.executable()),
                "mode": "llm" if agent_.llm else "offline"}

    @app.get("/v1/workflows")
    def workflows(_: str | None = Depends(principal), agent_: WorkflowAgent = Depends(get_agent)) -> list[dict[str, Any]]:
        return [{"id": w.id, "name": w.name, "trigger": w.trigger, "executable": w.executable,
                 "steps": w.steps_text, "inputs": {k: v.get("description", "") for k, v in w.inputs.items()},
                 "accepts_upload": any(v.get("upload") for v in w.inputs.values())}
                for w in agent_.registry.workflows.values()]

    def _run(fn: Callable[[], dict[str, Any]]) -> RunResponse:
        try:
            return to_response(fn())
        except RunNotFound as exc:
            raise HTTPException(404, "run not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/runs", response_model=RunResponse)
    def create_run(body: RunRequest, who: str | None = Depends(principal),
                   agent_: WorkflowAgent = Depends(get_agent)) -> RunResponse:
        return _run(lambda: agent_.run(body.request, principal=who))

    @app.post("/v1/runs/upload", response_model=RunResponse)
    def create_run_with_file(request: str = Form(..., min_length=1, max_length=10_000), file: UploadFile = File(...),
                             who: str | None = Depends(principal),
                             agent_: WorkflowAgent = Depends(get_agent)) -> RunResponse:
        path = save_upload(file, settings)
        return _run(lambda: agent_.run(request, attachments=[str(path)], principal=who))

    @app.post("/v1/runs/{run_id}/reply", response_model=RunResponse)
    def reply(run_id: str, body: ReplyRequest, who: str | None = Depends(principal),
              agent_: WorkflowAgent = Depends(get_agent)) -> RunResponse:
        return _run(lambda: agent_.resume(run_id, body.answer, principal=who))

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, who: str | None = Depends(principal),
                agent_: WorkflowAgent = Depends(get_agent)) -> dict[str, Any]:
        run = agent_.store.get_run(run_id)
        if run is None or (who is not None and run.get("principal") not in (None, who)):
            raise HTTPException(404, "run not found")
        return run

    @app.get("/v1/runs")
    def list_runs(limit: int = 50, status: str | None = None, who: str | None = Depends(principal),
                  agent_: WorkflowAgent = Depends(get_agent)) -> list[dict[str, Any]]:
        return agent_.store.list_runs(limit=max(1, min(limit, 500)), status=status, principal=who)

    return app
