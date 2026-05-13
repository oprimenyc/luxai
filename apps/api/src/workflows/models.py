"""Workflow domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class StepType(StrEnum):
    AGENT_RUN = "agent_run"
    HUMAN_INPUT = "human_input"
    CONDITION = "condition"
    PARALLEL = "parallel"
    WAIT = "wait"
    WEBHOOK = "webhook"


class WorkflowStep(BaseModel):
    id: str
    name: str
    type: StepType
    agent_id: str | None = None
    task_template: str = ""
    depends_on: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=300, ge=10)
    on_failure: str = "fail"  # "fail" | "continue" | "retry"
    condition: str | None = None  # Python expression evaluated against context
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    steps: list[WorkflowStep] = Field(min_length=1)
    schedule: str | None = None  # Cron expression
    context: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowStepExecution(BaseModel):
    step_id: str
    step_name: str
    status: StepStatus = StepStatus.PENDING
    session_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    retry_attempt: int = 0


class Workflow(WorkflowBase):
    id: UUID
    user_id: UUID
    status: WorkflowStatus = WorkflowStatus.DRAFT
    step_executions: list[WorkflowStepExecution] = Field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    current_step_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
