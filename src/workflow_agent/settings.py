"""Central configuration. Everything can be overridden through environment variables (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _path(env: str, default: str) -> Path:
    p = Path(os.getenv(env, default))
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    workflow_excel: Path = field(default_factory=lambda: _path("WORKFLOW_EXCEL", "data/AI_Agent_Workflow_Assessment.xlsx"))
    bindings_file: Path = field(default_factory=lambda: _path("WORKFLOW_BINDINGS", "config/workflow_bindings.yaml"))
    output_dir: Path = field(default_factory=lambda: _path("OUTPUT_DIR", "outputs"))
    run_log: Path = field(default_factory=lambda: _path("RUN_LOG", "runs/execution_log.csv"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "").strip().lower())
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "").strip())
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2")))
    # Routing below this confidence asks the user to clarify instead of guessing.
    min_route_confidence: float = field(default_factory=lambda: float(os.getenv("MIN_ROUTE_CONFIDENCE", "0.35")))
    force_offline: bool = field(default_factory=lambda: os.getenv("OFFLINE", "").lower() in {"1", "true", "yes"})


def get_settings() -> Settings:
    return Settings()
