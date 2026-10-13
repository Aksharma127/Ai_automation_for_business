import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workflow_agent.engine import WorkflowAgent  # noqa: E402
from workflow_agent.settings import Settings  # noqa: E402


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("run")
    return Settings(output_dir=tmp / "outputs", run_log=tmp / "runs" / "log.csv", force_offline=True)


@pytest.fixture(scope="session")
def agent(settings):
    return WorkflowAgent(settings=settings, llm=None)
