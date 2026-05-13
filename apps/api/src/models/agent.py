"""Agent domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    TERMINATED = "terminated"


class AgentCapability(StrEnum):
    WEB_SEARCH = "web_search"
    CODE_EXECUTION = "code_execution"
    FILE_OPERATIONS = "file_operations"
    DATABASE_QUERY = "database_query"
    EMAIL = "email"
    CALENDAR = "calendar"


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=500)
    capabilities: list[AgentCapability] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=10_000)
    model: str = Field(default="gpt-4o")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=200_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    capabilities: list[AgentCapability] | None = None
    system_prompt: str | None = Field(default=None, max_length=10_000)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    metadata: dict[str, Any] | None = None


class Agent(AgentBase):
    id: UUID
    user_id: UUID
    status: AgentStatus = AgentStatus.IDLE
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    agents: list[Agent]
    total: int
    page: int
    page_size: int
    has_more: bool
