"""Application configuration via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # ── Supabase ─────────────────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # ── JWT ──────────────────────────────────────────────────────────────
    supabase_jwt_secret: str

    # ── Orchestrator ─────────────────────────────────────────────────────
    orchestrator_url: str = "http://localhost:8001"
    orchestrator_api_key: str = ""

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── OpenAI ───────────────────────────────────────────────────────────
    openai_api_key: str = ""

    # ── Anthropic ────────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── LangSmith ────────────────────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "luxai"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
