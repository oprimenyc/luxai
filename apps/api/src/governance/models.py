"""Governance domain models — RBAC, policies, risk scoring, approvals."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


class Permission(StrEnum):
    # Agents
    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_RUN = "agent:run"
    AGENT_KILL = "agent:kill"

    # Sessions
    SESSION_CREATE = "session:create"
    SESSION_VIEW = "session:view"
    SESSION_CANCEL = "session:cancel"

    # Memory
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"

    # Governance
    APPROVAL_GRANT = "approval:grant"
    APPROVAL_DENY = "approval:deny"
    POLICY_MANAGE = "policy:manage"
    KILL_SWITCH = "kill_switch:activate"

    # System
    AUDIT_VIEW = "audit:view"
    SYSTEM_CONFIG = "system:config"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.SESSION_VIEW,
        Permission.MEMORY_READ,
        Permission.AUDIT_VIEW,
    },
    Role.OPERATOR: {
        Permission.AGENT_RUN,
        Permission.SESSION_CREATE,
        Permission.SESSION_VIEW,
        Permission.SESSION_CANCEL,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
    },
    Role.ADMIN: {
        Permission.AGENT_CREATE,
        Permission.AGENT_UPDATE,
        Permission.AGENT_DELETE,
        Permission.AGENT_RUN,
        Permission.AGENT_KILL,
        Permission.SESSION_CREATE,
        Permission.SESSION_VIEW,
        Permission.SESSION_CANCEL,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.MEMORY_DELETE,
        Permission.APPROVAL_GRANT,
        Permission.APPROVAL_DENY,
        Permission.AUDIT_VIEW,
    },
    Role.OWNER: set(Permission),
    Role.AUDITOR: {Permission.AUDIT_VIEW, Permission.SESSION_VIEW},
}


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


class ExecutionPolicy(BaseModel):
    name: str
    description: str
    enabled: bool = True
    max_iterations: int = Field(default=25, ge=1, le=100)
    max_tokens_per_session: int = Field(default=500_000)
    max_duration_seconds: int = Field(default=600)
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    require_approval_above_risk: RiskLevel = RiskLevel.HIGH
    retry_budget: int = Field(default=3, ge=0, le=10)
    sandbox_enabled: bool = True


class RiskFactor(BaseModel):
    name: str
    score: float  # 0.0 - 1.0
    reason: str


class RiskAssessment(BaseModel):
    session_id: str
    agent_id: str
    task_preview: str
    risk_score: float  # 0.0 - 1.0
    risk_level: RiskLevel
    factors: list[RiskFactor]
    requires_approval: bool
    policy_triggered: str | None = None
    assessed_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalRequest(BaseModel):
    id: UUID
    session_id: str
    agent_id: str
    user_id: str
    risk_assessment: RiskAssessment
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    denial_reason: str | None = None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
