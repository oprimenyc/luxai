"""Application configuration via pydantic-settings."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "LuxAI API"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False

    # ── CORS ─────────────────────────────────────────────────────────────
    # Stored as a plain str to avoid pydantic_settings v2 JSON-parsing list
    # fields before field validators run. The public `cors_origins` property
    # returns the parsed list and is used by the CORS middleware in main.py.
    # Accepts either comma-separated ("a,b") or JSON array ('["a","b"]').
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("cors_origins"),
    )

    @property
    def cors_origins(self) -> list[str]:
        """Return CORS origins as a list regardless of how they were stored."""
        v = self.cors_origins_raw.strip()
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
            except (json.JSONDecodeError, ValueError):
                pass
        return [o.strip() for o in v.split(",") if o.strip()]

    # ── Supabase ─────────────────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # ── JWT ──────────────────────────────────────────────────────────────
    supabase_jwt_secret: str

    # ── Orchestrator ─────────────────────────────────────────────────────
    orchestrator_url: str = "http://localhost:8001"
    orchestrator_api_key: str = ""

    # ── Redis (Upstash) ──────────────────────────────────────────────────
    # Reads UPSTASH_REDIS_URL from env (rediss://default:<token>@<host>.upstash.io:6379)
    redis_url: str = Field(
        default="",
        validation_alias=AliasChoices("upstash_redis_url"),
    )

    # ── OpenAI ───────────────────────────────────────────────────────────
    openai_api_key: str = ""

    # ── Anthropic ────────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── DeepSeek (TradingAgents analyst LLM — OpenAI-compat API) ────────────
    deepseek_api_key: str = ""

    # ── LangSmith ────────────────────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "luxai"

    # ── Alpaca Paper Trading ──────────────────────────────────────────────
    # IMPORTANT: These keys must be for Alpaca PAPER trading accounts only.
    # The trading engine enforces paper mode programmatically and will
    # raise an error if a live account is detected.
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    # Explicit paper-mode intent flag. Defaults to True (safe default).
    # Startup verification in src/core/startup_checks.py refuses to boot
    # if this is False, or if the live Alpaca account is not paper_trading.
    alpaca_paper: bool = True

    # ── Tradier (future integration) ─────────────────────────────────────
    tradier_api_key: str = ""
    tradier_sandbox: bool = True  # always sandbox unless explicitly overridden

    # ── OTLP Tracing ─────────────────────────────────────────────────────
    otlp_endpoint: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
