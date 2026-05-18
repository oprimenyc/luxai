"""Risk engine, policy evaluation, and approval gate."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog

from src.events.bus import event_bus
from src.events.models import ApprovalRequiredEvent, KillSwitchEvent, RiskFlaggedEvent
from src.governance.models import (
    ApprovalRequest,
    ApprovalStatus,
    ExecutionPolicy,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)

log = structlog.get_logger(__name__)

# ── Risk scoring heuristics ───────────────────────────────────────────────────

_HIGH_RISK_PATTERNS = [
    r"\b(delete|drop|truncate|destroy|wipe|erase)\b.*\b(database|table|collection|bucket)\b",
    r"\b(send|publish|broadcast|notify|email|sms)\b.*\b(all|everyone|bulk)\b",
    r"\b(execute|run|shell|bash|subprocess|eval)\b",
    r"\b(admin|root|sudo|privilege)\b",
    r"\b(payment|charge|transfer|withdraw|debit)\b",
    r"\b(secret|password|credential|api.key|token)\b.*\b(log|print|output|return)\b",
]

_MEDIUM_RISK_PATTERNS = [
    r"\b(update|modify|change|alter)\b.*\b(user|account|permission|role)\b",
    r"\b(external|third.party|webhook|http)\b",
    r"\b(loop|recursive|infinite|retry)\b",
    r"\b(concurrent|parallel|multithread)\b",
]

_HIGH_RISK_TOOLS = {"shell_exec", "database_write", "file_delete", "email_send", "payment_charge"}
_MEDIUM_RISK_TOOLS = {"web_search", "file_write", "database_read", "api_call"}


class RiskEngine:
    """Score tasks against configured policies."""

    def __init__(self, policy: ExecutionPolicy | None = None) -> None:
        self._policy = policy or ExecutionPolicy(
            name="default",
            description="Default system policy",
        )

    def assess(
        self,
        session_id: str,
        agent_id: str,
        task: str,
        requested_tools: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        factors: list[RiskFactor] = []
        task_lower = task.lower()

        # Pattern-based scoring
        for pattern in _HIGH_RISK_PATTERNS:
            if re.search(pattern, task_lower, re.IGNORECASE):
                factors.append(RiskFactor(
                    name=f"high_risk_pattern",
                    score=0.7,
                    reason=f"Task matches high-risk pattern: {pattern}",
                ))

        for pattern in _MEDIUM_RISK_PATTERNS:
            if re.search(pattern, task_lower, re.IGNORECASE):
                factors.append(RiskFactor(
                    name="medium_risk_pattern",
                    score=0.4,
                    reason=f"Task matches medium-risk pattern: {pattern}",
                ))

        # Tool-based scoring
        tools = set(requested_tools or [])
        blocked = tools & set(self._policy.blocked_tools)
        if blocked:
            factors.append(RiskFactor(
                name="blocked_tool",
                score=1.0,
                reason=f"Blocked tools requested: {blocked}",
            ))

        high_risk_tools_used = tools & _HIGH_RISK_TOOLS
        if high_risk_tools_used:
            factors.append(RiskFactor(
                name="high_risk_tool",
                score=0.6,
                reason=f"High-risk tools: {high_risk_tools_used}",
            ))

        medium_risk_tools_used = tools & _MEDIUM_RISK_TOOLS
        if medium_risk_tools_used:
            factors.append(RiskFactor(
                name="medium_risk_tool",
                score=0.3,
                reason=f"Medium-risk tools: {medium_risk_tools_used}",
            ))

        # Length heuristic — very long tasks may indicate scope creep
        if len(task) > 2000:
            factors.append(RiskFactor(
                name="large_task_scope",
                score=0.2,
                reason="Task description is unusually long",
            ))

        # Compute aggregate score (max of individual + sum penalty)
        if not factors:
            risk_score = 0.1
        else:
            max_score = max(f.score for f in factors)
            sum_penalty = min(sum(f.score for f in factors) * 0.1, 0.3)
            risk_score = min(max_score + sum_penalty, 1.0)

        risk_level = self._score_to_level(risk_score)
        requires_approval = self._requires_approval(risk_level)
        policy_triggered = self._policy.name if requires_approval else None

        return RiskAssessment(
            session_id=session_id,
            agent_id=agent_id,
            task_preview=task[:300],
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            factors=factors,
            requires_approval=requires_approval,
            policy_triggered=policy_triggered,
        )

    def _score_to_level(self, score: float) -> RiskLevel:
        if score >= 0.8:
            return RiskLevel.CRITICAL
        if score >= 0.5:
            return RiskLevel.HIGH
        if score >= 0.25:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _requires_approval(self, level: RiskLevel) -> bool:
        threshold_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        policy_threshold = self._policy.require_approval_above_risk
        return threshold_order.index(level) >= threshold_order.index(policy_threshold)


class ApprovalGate:
    """Manages approval workflows for high-risk executions."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}  # session_id → request

    async def request_approval(
        self,
        assessment: RiskAssessment,
        user_id: str,
        approvers: list[str] | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            id=uuid4(),
            session_id=assessment.session_id,
            agent_id=assessment.agent_id,
            user_id=user_id,
            risk_assessment=assessment,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        self._pending[assessment.session_id] = request

        await event_bus.publish(
            ApprovalRequiredEvent(
                session_id=assessment.session_id,
                agent_id=assessment.agent_id,
                user_id=user_id,
                payload={
                    "approval_id": str(request.id),
                    "risk_score": assessment.risk_score,
                    "risk_level": assessment.risk_level.value,
                    "policy_name": assessment.policy_triggered,
                    "action": assessment.task_preview,
                    "approvers": approvers or [],
                    "expires_at": request.expires_at.isoformat(),
                },
            )
        )

        log.warning(
            "approval_requested",
            session_id=assessment.session_id,
            risk_score=assessment.risk_score,
        )
        return request

    async def resolve(
        self,
        session_id: str,
        approved: bool,
        resolved_by: str,
        reason: str | None = None,
    ) -> ApprovalRequest | None:
        request = self._pending.pop(session_id, None)
        if not request:
            return None

        if datetime.now(UTC) > request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            return request

        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        request.approved_by = resolved_by
        request.denial_reason = reason
        request.resolved_at = datetime.now(UTC)

        log.info(
            "approval_resolved",
            session_id=session_id,
            approved=approved,
            resolved_by=resolved_by,
        )
        return request

    async def activate_kill_switch(
        self,
        session_ids: list[str],
        reason: str,
        activated_by: str,
    ) -> None:
        for session_id in session_ids:
            self._pending.pop(session_id, None)

        await event_bus.publish(
            KillSwitchEvent(
                user_id=activated_by,
                payload={
                    "reason": reason,
                    "activated_by": activated_by,
                    "affected_sessions": session_ids,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )
        log.critical(
            "kill_switch_activated",
            sessions=session_ids,
            reason=reason,
            by=activated_by,
        )

    def get_pending(self, session_id: str) -> ApprovalRequest | None:
        req = self._pending.get(session_id)
        if req and datetime.now(UTC) > req.expires_at:
            req.status = ApprovalStatus.EXPIRED
            self._pending.pop(session_id, None)
            return None
        return req


# ── Singletons ────────────────────────────────────────────────────────────────
risk_engine = RiskEngine()
approval_gate = ApprovalGate()
