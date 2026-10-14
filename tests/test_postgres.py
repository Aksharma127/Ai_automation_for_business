"""PostgreSQL run history + checkpoints. Runs when TEST_DATABASE_URL points at a database (CI does)."""
import dataclasses
import os

import pytest

from workflow_agent.engine import WorkflowAgent

PG = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not PG, reason="set TEST_DATABASE_URL=postgresql://... to run")


def test_paused_run_survives_a_restart(settings):
    s = dataclasses.replace(settings, database_url=PG, checkpoint_url="")
    first = WorkflowAgent(settings=s, llm=None)
    paused = first.run("Where is my order?", principal="key-pg")
    assert paused["awaiting_reply"]
    first.close()

    second = WorkflowAgent(settings=s, llm=None)  # a new process: only the database is shared
    done = second.resume(paused["run_id"], "ORD-1001", principal="key-pg")
    assert done["status"] == "completed"
    stored = second.store.get_run(paused["run_id"])
    assert stored["status"] == "completed" and stored["steps"]
    assert any(r["run_id"] == paused["run_id"] for r in second.store.list_runs(principal="key-pg"))
    assert any(row["workflow_id"] == "WF005" for row in second.store.step_log())
    second.close()
