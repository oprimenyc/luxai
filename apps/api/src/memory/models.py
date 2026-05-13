"""Memory domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    SEMANTIC = "semantic"       # Facts, concepts, knowledge
    EPISODIC = "episodic"       # Past interactions, events
    WORKFLOW = "workflow"       # Task execution context
    USER = "user"               # User preferences, profile
    PROJECT = "project"         # Project-specific context
    STRATEGIC = "strategic"     # High-level goals, strategy


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    COMPRESSED = "compressed"
    EVICTED = "evicted"


class MemoryBase(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    memory_type: MemoryType
    agent_id: str | None = None
    session_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: datetime | None = None


class MemoryCreate(MemoryBase):
    pass


class Memory(MemoryBase):
    id: UUID
    user_id: UUID
    status: MemoryStatus = MemoryStatus.ACTIVE
    embedding_model: str = "text-embedding-3-small"
    access_count: int = 0
    last_accessed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemorySearchResult(BaseModel):
    memory: Memory
    similarity_score: float
    rank: int


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    memory_types: list[MemoryType] | None = None
    agent_id: str | None = None
    session_id: str | None = None
    tags: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.6, ge=0.0, le=1.0)
    include_archived: bool = False
