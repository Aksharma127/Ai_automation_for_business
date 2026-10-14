"""Run history: every run and every executed step, in SQLite (default) or PostgreSQL.

Used by the API (``GET /runs/{id}``), for audit, and by WF010, which can analyse the agent's
own history via the ``runstore://steps`` data source.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        principal TEXT,
        request TEXT NOT NULL,
        workflow_id TEXT,
        workflow_name TEXT,
        status TEXT NOT NULL,
        route_method TEXT,
        route_confidence REAL,
        answer TEXT,
        inputs_json TEXT,
        result_json TEXT,
        notes_json TEXT,
        llm_calls INTEGER DEFAULT 0,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0,
        duration_ms REAL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS run_steps (
        run_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        step_no INTEGER NOT NULL,
        step TEXT NOT NULL,
        tool TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER,
        duration_ms REAL,
        output TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (run_id, seq)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_steps_run ON run_steps (run_id)",
]

RUN_COLS = ["run_id", "created_at", "updated_at", "principal", "request", "workflow_id", "workflow_name", "status",
            "route_method", "route_confidence", "answer", "inputs_json", "result_json", "notes_json", "llm_calls",
            "input_tokens", "output_tokens", "cost_usd", "duration_ms"]
OK_STEP_STATUSES = {"ok", "degraded", "needs_input", "escalated", "user_reply"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class RunStore:
    def __init__(self, url: str):
        self.url = url
        self._lock = threading.Lock()
        if url.startswith("sqlite"):
            path = url.split("sqlite:///", 1)[-1] if "sqlite:///" in url else ":memory:"
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn: Any = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._ph = "?"
            self._pg = False
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg
            from psycopg.rows import dict_row

            self._conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
            self._ph = "%s"
            self._pg = True
        else:
            raise ValueError(f"unsupported DATABASE_URL scheme: {url.split(':', 1)[0]}")
        with self._lock:
            for stmt in SCHEMA:
                self._conn.execute(stmt)
            self._commit()

    def _commit(self) -> None:
        if not self._pg:
            self._conn.commit()

    def _q(self, sql: str) -> str:
        return sql.replace("?", self._ph)

    def ping(self) -> bool:
        with self._lock:
            self._conn.execute("SELECT 1")
        return True

    # -- writes ------------------------------------------------------------------------------
    def save_run(self, state: dict[str, Any], *, principal: str | None = None, usage: dict[str, Any] | None = None,
                 duration_ms: float = 0.0) -> None:
        usage = usage or {}
        route = state.get("route") or {}
        now = _now()
        row = {
            "run_id": state["run_id"], "created_at": now, "updated_at": now, "principal": principal,
            "request": state.get("request", ""), "workflow_id": state.get("workflow_id"),
            "workflow_name": state.get("workflow_name"), "status": state.get("status", "unknown"),
            "route_method": route.get("method"), "route_confidence": route.get("confidence"),
            "answer": state.get("answer"),
            "inputs_json": json.dumps(state.get("inputs"), default=str),
            "result_json": json.dumps(state.get("result"), default=str),
            "notes_json": json.dumps(state.get("notes") or [], default=str),
            "llm_calls": usage.get("llm_calls", 0), "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0), "cost_usd": usage.get("cost_usd", 0.0),
            "duration_ms": duration_ms,
        }
        updatable = [c for c in RUN_COLS if c not in {"run_id", "created_at", "principal"}]
        # accumulate usage across resumed segments of the same run
        acc = {"llm_calls", "input_tokens", "output_tokens", "cost_usd", "duration_ms"}
        sets = ", ".join(f"{c} = runs.{c} + excluded.{c}" if c in acc else f"{c} = excluded.{c}" for c in updatable)
        sql = (f"INSERT INTO runs ({', '.join(RUN_COLS)}) VALUES ({', '.join('?' for _ in RUN_COLS)}) "
               f"ON CONFLICT (run_id) DO UPDATE SET {sets}")
        with self._lock:
            self._conn.execute(self._q(sql), [row[c] for c in RUN_COLS])
            self._conn.execute(self._q("DELETE FROM run_steps WHERE run_id = ?"), [state["run_id"]])
            for seq, t in enumerate(state.get("trace") or [], start=1):
                self._conn.execute(self._q(
                    "INSERT INTO run_steps (run_id, seq, step_no, step, tool, status, attempts, duration_ms, output, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"),
                    [state["run_id"], seq, t.get("n", 0), t.get("step", ""), t.get("tool", ""), t.get("status", ""),
                     t.get("attempts"), t.get("ms"), str(t.get("output", ""))[:4000], now])
            self._commit()

    # -- reads -------------------------------------------------------------------------------
    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(self._q(sql), params)
            return [dict(r) for r in cur.fetchall()]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM runs WHERE run_id = ?", [run_id])
        if not rows:
            return None
        run = rows[0]
        for k in ("inputs_json", "result_json", "notes_json"):
            run[k.removesuffix("_json")] = json.loads(run.pop(k) or "null")
        run["steps"] = self._rows("SELECT step_no, step, tool, status, attempts, duration_ms, output FROM run_steps "
                                  "WHERE run_id = ? ORDER BY seq", [run_id])
        return run

    def list_runs(self, limit: int = 50, status: str | None = None, principal: str | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if principal:
            where.append("principal = ?")
            params.append(principal)
        sql = ("SELECT run_id, created_at, updated_at, request, workflow_id, status, cost_usd, duration_ms FROM runs"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT ?")
        return self._rows(sql, params + [int(limit)])

    def step_log(self) -> list[dict[str, Any]]:
        """All executed steps in the execution-log format WF010 analyses."""
        rows = self._rows(
            "SELECT s.run_id, s.created_at AS timestamp, r.workflow_id, r.workflow_name, s.step, s.status, "
            "s.duration_ms, s.output FROM run_steps s JOIN runs r ON r.run_id = s.run_id "
            "WHERE r.workflow_id IS NOT NULL ORDER BY s.created_at, s.seq", [])
        out = []
        for r in rows:
            ok = r["status"] in OK_STEP_STATUSES
            out.append({"run_id": r["run_id"], "timestamp": r["timestamp"], "workflow_id": r["workflow_id"],
                        "workflow_name": r["workflow_name"], "step": r["step"], "status": "success" if ok else "failed",
                        "duration_sec": round((r["duration_ms"] or 0) / 1000, 3),
                        "error_message": "" if ok else (r["output"] or "")})
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()
