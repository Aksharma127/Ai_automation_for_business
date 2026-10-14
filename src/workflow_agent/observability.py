"""Structured logging and tracing.

* Logs: stdlib ``logging``; ``LOG_JSON=1`` switches to one JSON object per line (for log
  shippers). Every record emitted inside a run carries its ``run_id``.
* Traces: OpenTelemetry spans per run and per step when ``opentelemetry`` is installed and an
  SDK/exporter is configured (otherwise the API is a no-op). LangChain/LangGraph calls are
  also traced to LangSmith when ``LANGSMITH_TRACING=true`` is set.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("workflow_agent")
current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_run_id", default=None)

try:  # optional dependency
    from opentelemetry import trace as _otel_trace

    _tracer: Any = _otel_trace.get_tracer("workflow_agent")
except ImportError:  # pragma: no cover - depends on environment
    _tracer = None

_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = getattr(record, "run_id", None) or current_run_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        data.update({k: v for k, v in vars(record).items() if k not in _RESERVED and v is not None})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra = {k: v for k, v in vars(record).items() if k not in _RESERVED and v is not None}
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.getMessage()}"
        return base + (" " + " ".join(f"{k}={v}" for k, v in extra.items()) if extra else "")


_configured = False


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_logs else TextFormatter())
    handler.addFilter(_RunIdFilter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    _configured = True


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """An OpenTelemetry span (no-op when OpenTelemetry is not installed)."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(f"workflow.{k}", v if isinstance(v, (str, int, float, bool)) else str(v))
        yield s
