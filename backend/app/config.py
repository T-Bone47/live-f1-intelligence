"""Application configuration via environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://f1intel:f1intel_dev@localhost:5433/f1intel"

    openf1_base_url: str = "https://api.openf1.org"
    # Documented free-tier limits are 3 rps / 30 rpm, but empirical 2026-08
    # testing hits HTTP 429 well before those numbers - defaults below are
    # deliberately conservative.
    openf1_rate_limit_rps: float = 1.8
    openf1_rate_limit_rpm: float = 20.0
    openf1_api_token: str | None = None

    # Direct F1 livetiming SignalR feed (Phase 1.5): disabled by default.
    signalr_enabled: bool = False
    f1_bearer_token: str | None = None

    # --- Phase 6: grounded LLM race engineer ---
    # Default provider "mock" answers deterministically from context packs
    # (no network, no key). Set to openai-compatible + base/key/model for a
    # real model. Keys stay server-side only.
    llm_provider: str = "mock"
    llm_model: str = "mock-grounded-1"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_auto_commentary: bool = True
    llm_min_call_interval_s: float = 0.0
    gemini_api_key: str | None = None

    poll_interval_seconds: float = 6.0
    recordings_dir: Path = BACKEND_ROOT.parent / "recordings"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
