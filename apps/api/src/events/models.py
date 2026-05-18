"""Typed event contracts for the LuxAI event bus."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    # Agent lifecycle
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_STATUS_CHANGED = "agent.status_changed"

    # Session lifecycle
    SESSION_CREATED = "session.created"
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    SESSION_CANCELLED = "session.cancelled"

    # Orchestration
    GRAPH_NODE_ENTERED = "graph.node_entered"
    GRAPH_NODE_EXITED = "graph.node_exited"
    GRAPH_EDGE_TRAVERSED = "graph.edge_traversed"
    GRAPH_COMPLETED = "graph.completed"

    # Token + latency telemetry
    TOKEN_USAGE = "telemetry.token_usage"
    LATENCY_RECORDED = "telemetry.latency"
    RETRY_OCCURRED = "telemetry.retry"

    # Memory
    MEMORY_STORED = "memory.stored"
    MEMORY_RETRIEVED = "memory.retrieved"
    MEMORY_EVICTED = "memory.evicted"

    # Governance
    APPROVAL_REQUIRED = "governance.approval_required"
    APPROVAL_GRANTED = "governance.approval_granted"
    APPROVAL_DENIED = "governance.approval_denied"
    KILL_SWITCH_ACTIVATED = "governance.kill_switch"
    RISK_FLAGGED = "governance.risk_flagged"

    # Workflow
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_STEP_STARTED = "workflow.step_started"
    WORKFLOW_STEP_COMPLETED = "workflow.step_completed"
    WORKFLOW_CHECKPOINT = "workflow.checkpoint"
    WORKFLOW_RECOVERED = "workflow.recovered"

    # Workflow
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Trading (paper/simulation only — no live trading events)
    TRADE_ORDER_SUBMITTED = "trade.order_submitted"
    TRADE_ORDER_FILLED = "trade.order_filled"
    TRADE_ORDER_CANCELLED = "trade.order_cancelled"
    TRADE_ORDER_REJECTED = "trade.order_rejected"
    TRADE_POSITION_OPENED = "trade.position_opened"
    TRADE_POSITION_CLOSED = "trade.position_closed"
    TRADE_PNL_RECORDED = "trade.pnl_recorded"
    TRADE_RISK_TRIGGERED = "trade.risk_triggered"
    TRADE_DAILY_LOSS_HALTED = "trade.daily_loss_halted"
    TRADE_PORTFOLIO_SNAPSHOT = "trade.portfolio_snapshot"
    TRADE_REPLAY_COMPLETED = "trade.replay_completed"

    # System
    SYSTEM_HEARTBEAT = "system.heartbeat"
    SYSTEM_ERROR = "system.error"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class BaseEvent(BaseModel):
    """Root event envelope — all events extend this."""

    id: UUID = Field(default_factory=uuid4)
    type: EventType
    severity: EventSeverity = EventSeverity.INFO
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Orchestration Events ──────────────────────────────────────────────────────

class GraphNodeEnteredEvent(BaseEvent):
    type: Literal[EventType.GRAPH_NODE_ENTERED] = EventType.GRAPH_NODE_ENTERED
    payload: dict[str, Any]  # node_name, iteration, state_snapshot


class GraphNodeExitedEvent(BaseEvent):
    type: Literal[EventType.GRAPH_NODE_EXITED] = EventType.GRAPH_NODE_EXITED
    payload: dict[str, Any]  # node_name, duration_ms, output_preview


class TokenUsageEvent(BaseEvent):
    type: Literal[EventType.TOKEN_USAGE] = EventType.TOKEN_USAGE
    payload: dict[str, Any]  # model, input_tokens, output_tokens, cost_usd


class LatencyEvent(BaseEvent):
    type: Literal[EventType.LATENCY_RECORDED] = EventType.LATENCY_RECORDED
    payload: dict[str, Any]  # operation, duration_ms, p50, p95, p99


class RetryEvent(BaseEvent):
    type: Literal[EventType.RETRY_OCCURRED] = EventType.RETRY_OCCURRED
    severity: EventSeverity = EventSeverity.WARNING
    payload: dict[str, Any]  # attempt, max_attempts, error, backoff_ms


# ── Memory Events ─────────────────────────────────────────────────────────────

class MemoryStoredEvent(BaseEvent):
    type: Literal[EventType.MEMORY_STORED] = EventType.MEMORY_STORED
    payload: dict[str, Any]  # memory_id, memory_type, content_preview, embedding_model


class MemoryRetrievedEvent(BaseEvent):
    type: Literal[EventType.MEMORY_RETRIEVED] = EventType.MEMORY_RETRIEVED
    payload: dict[str, Any]  # memory_ids, scores, query_preview


# ── Governance Events ─────────────────────────────────────────────────────────

class ApprovalRequiredEvent(BaseEvent):
    type: Literal[EventType.APPROVAL_REQUIRED] = EventType.APPROVAL_REQUIRED
    severity: EventSeverity = EventSeverity.WARNING
    payload: dict[str, Any]  # risk_score, policy_name, action, approvers


class RiskFlaggedEvent(BaseEvent):
    type: Literal[EventType.RISK_FLAGGED] = EventType.RISK_FLAGGED
    severity: EventSeverity = EventSeverity.WARNING
    payload: dict[str, Any]  # risk_score, risk_factors, policy_triggered


class KillSwitchEvent(BaseEvent):
    type: Literal[EventType.KILL_SWITCH_ACTIVATED] = EventType.KILL_SWITCH_ACTIVATED
    severity: EventSeverity = EventSeverity.CRITICAL
    payload: dict[str, Any]  # reason, activated_by, affected_sessions


# ── Wire format ───────────────────────────────────────────────────────────────

class EventEnvelope(BaseModel):
    """WebSocket/SSE wire format."""
    event: BaseEvent
    sequence: int
    replay: bool = False
