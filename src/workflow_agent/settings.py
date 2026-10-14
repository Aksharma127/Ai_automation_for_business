"""Central configuration. Everything can be overridden through environment variables (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _root() -> Path:
    """Project root: APP_ROOT, else the source checkout, else the working directory (installed package)."""
    if os.getenv("APP_ROOT"):
        return Path(os.environ["APP_ROOT"]).resolve()
    checkout = Path(__file__).resolve().parents[2]
    return checkout if (checkout / "config").is_dir() else Path.cwd()


ROOT = _root()
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    """Environment value; empty counts as unset so a copied .env.example keeps the defaults."""
    return os.getenv(name) or default


def _path(env: str, default: str) -> Path:
    p = Path(_env(env, default))
    return p if p.is_absolute() else ROOT / p


def _bool(env: str, default: bool = False) -> bool:
    v = os.getenv(env)
    return default if v is None or v == "" else v.strip().lower() in {"1", "true", "yes", "on"}


def _list(env: str, default: str = "") -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(env, default).split(",") if x.strip())


def _float(env: str, default: float) -> float:
    v = os.getenv(env)
    return float(v) if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("APP_ENV", "development").lower())

    # --- workflow sources & outputs -------------------------------------------------------
    workflow_excel: Path = field(default_factory=lambda: _path("WORKFLOW_EXCEL", "data/AI_Agent_Workflow_Assessment.xlsx"))
    bindings_file: Path = field(default_factory=lambda: _path("WORKFLOW_BINDINGS", "config/workflow_bindings.yaml"))
    output_dir: Path = field(default_factory=lambda: _path("OUTPUT_DIR", "outputs"))
    upload_dir: Path = field(default_factory=lambda: _path("UPLOAD_DIR", "runs/uploads"))
    # Tools may only read files under these directories (relative to the repo root or absolute).
    allowed_data_dirs: tuple[str, ...] = field(default_factory=lambda: _list("ALLOWED_DATA_DIRS", "data,runs,outputs"))
    # Tools may only fetch http(s) data sources from these hosts (empty = no remote sources).
    allowed_source_hosts: tuple[str, ...] = field(default_factory=lambda: _list("ALLOWED_SOURCE_HOSTS"))

    # --- persistence ----------------------------------------------------------------------
    # sqlite:///path or postgresql://... ; run history (runs + steps) and LangGraph checkpoints
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{ROOT / 'runs' / 'agent.db'}"))
    checkpoint_url: str = field(default_factory=lambda: _env("CHECKPOINT_URL", ""))  # defaults to DATABASE_URL

    # --- LLM ------------------------------------------------------------------------------
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "").strip().lower())
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "").strip())
    llm_temperature: float = field(default_factory=lambda: _float("LLM_TEMPERATURE", 0.2))
    llm_timeout_sec: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SEC", 60))
    llm_requests_per_second: float = field(default_factory=lambda: _float("LLM_REQUESTS_PER_SECOND", 5))
    max_llm_calls_per_run: int = field(default_factory=lambda: int(_float("MAX_LLM_CALLS_PER_RUN", 20)))
    max_llm_cost_per_run_usd: float = field(default_factory=lambda: _float("MAX_LLM_COST_PER_RUN_USD", 0.50))
    # USD per 1M tokens, overrides the built-in price table (llm.PRICES)
    llm_price_input: float | None = field(default_factory=lambda: _float("LLM_PRICE_INPUT_PER_MTOK", -1) if os.getenv("LLM_PRICE_INPUT_PER_MTOK") else None)
    llm_price_output: float | None = field(default_factory=lambda: _float("LLM_PRICE_OUTPUT_PER_MTOK", -1) if os.getenv("LLM_PRICE_OUTPUT_PER_MTOK") else None)
    force_offline: bool = field(default_factory=lambda: _bool("OFFLINE"))

    # --- agent behaviour ------------------------------------------------------------------
    min_route_confidence: float = field(default_factory=lambda: _float("MIN_ROUTE_CONFIDENCE", 0.35))
    step_timeout_sec: float = field(default_factory=lambda: _float("STEP_TIMEOUT_SEC", 30))
    max_request_chars: int = field(default_factory=lambda: int(_float("MAX_REQUEST_CHARS", 2000)))

    # --- integrations (empty = use the simulated file-backed services) --------------------
    orders_api_url: str = field(default_factory=lambda: _env("ORDERS_API_URL", "").rstrip("/"))
    orders_api_token: str = field(default_factory=lambda: _env("ORDERS_API_TOKEN", ""))
    carrier_api_url: str = field(default_factory=lambda: _env("CARRIER_API_URL", "").rstrip("/"))
    carrier_api_token: str = field(default_factory=lambda: _env("CARRIER_API_TOKEN", ""))
    http_timeout_sec: float = field(default_factory=lambda: _float("HTTP_TIMEOUT_SEC", 10))

    # --- API ------------------------------------------------------------------------------
    api_keys: tuple[str, ...] = field(default_factory=lambda: _list("API_KEYS"))
    auth_disabled: bool = field(default_factory=lambda: _bool("AUTH_DISABLED"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_float("RATE_LIMIT_PER_MINUTE", 60)))
    max_upload_mb: float = field(default_factory=lambda: _float("MAX_UPLOAD_MB", 10))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: _list("CORS_ORIGINS"))

    # --- logging --------------------------------------------------------------------------
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", default=False))

    @property
    def is_production(self) -> bool:
        return self.env in {"production", "prod"}

    def validate(self) -> list[str]:
        """Configuration problems that should stop a production deployment."""
        problems = []
        if self.is_production:
            if not self.api_keys and not self.auth_disabled:
                problems.append("API_KEYS must be set in production (or AUTH_DISABLED=1 behind a trusted gateway)")
            if self.database_url.startswith("sqlite") and not _bool("ALLOW_SQLITE_IN_PRODUCTION"):
                problems.append("use a PostgreSQL DATABASE_URL in production (or ALLOW_SQLITE_IN_PRODUCTION=1)")
        return problems


def get_settings() -> Settings:
    return Settings()
