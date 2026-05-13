"""Orchestrator configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LuxAI Orchestrator"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    port: int = Field(default=8001, ge=1, le=65535)

    # ── LLM ──────────────────────────────────────────────────────────────
    openai_api_key: str
    anthropic_api_key: str = ""
    default_model: str = "gpt-4o"
    fallback_model: str = "claude-3-5-sonnet-20241022"

    # ── LangSmith ────────────────────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "luxai-orchestrator"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/1"

    # ── Security ──────────────────────────────────────────────────────────
    api_key: str = ""

    # ── Limits ───────────────────────────────────────────────────────────
    max_iterations: int = Field(default=25, ge=1, le=100)
    max_tokens_per_step: int = Field(default=8192, ge=1)
    request_timeout_seconds: int = Field(default=300, ge=30)

    # ── Per-agent models ─────────────────────────────────────────────────
    critic_model: str = "gpt-4o"
    researcher_model: str = "gpt-4o"
    executor_model: str = "gpt-4o-mini"

    # ── Service URLs ─────────────────────────────────────────────────────
    orchestrator_url: str = "http://localhost:8001"
    api_service_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> OrchestratorSettings:
    return OrchestratorSettings()  # type: ignore[call-arg]


settings = get_settings()
