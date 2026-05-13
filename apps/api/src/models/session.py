"""Session domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: MessageRole
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionBase(BaseModel):
    agent_id: UUID
    task: str = Field(min_length=1, max_length=10_000)
    context: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(SessionBase):
    pass


class Session(SessionBase):
    id: UUID
    user_id: UUID
    status: SessionStatus = SessionStatus.PENDING
    messages: list[Message] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
