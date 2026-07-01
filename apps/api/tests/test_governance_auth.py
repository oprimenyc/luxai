"""
Path: apps/api/tests/test_governance_auth.py
Security: Verifies governance approval resolution stays scoped to the owner or
          an admin, and that governance kill-switch activation is admin-only.
Scale: Pure unit tests with mocked in-memory gate state; no network or DB I/O.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import UTC, datetime, timedelta
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.governance.models import ApprovalRequest, ApprovalStatus, RiskAssessment, RiskLevel
from src.governance.router import (
    KillSwitchRequest,
    ResolveApprovalRequest,
    activate_kill_switch,
    resolve_approval,
)
from src.middleware.auth import AuthenticatedUser


def _user(user_id: str, role: str = "authenticated") -> AuthenticatedUser:
    return AuthenticatedUser(user_id=UUID(user_id), email=f"{role}@example.com", role=role)


def _approval(user_id: str) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid4(),
        session_id="session-1",
        agent_id="agent-1",
        user_id=user_id,
        risk_assessment=RiskAssessment(
            session_id="session-1",
            agent_id="agent-1",
            task_preview="test",
            risk_score=0.6,
            risk_level=RiskLevel.HIGH,
            factors=[],
            requires_approval=True,
            policy_triggered="default",
        ),
        status=ApprovalStatus.PENDING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )


@pytest.mark.asyncio
async def test_resolve_approval_rejects_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    pending = _approval("12345678-1234-5678-1234-567812345678")
    gate = SimpleNamespace(
        get_pending=lambda session_id: pending,
        resolve=AsyncMock(),
    )
    monkeypatch.setattr("src.governance.router.approval_gate", gate)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_approval(
            "session-1",
            ResolveApprovalRequest(approved=True),
            _user("87654321-4321-8765-4321-876543218765"),
        )

    assert exc_info.value.status_code == 403
    gate.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_approval_allows_admin_for_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    pending = _approval("12345678-1234-5678-1234-567812345678")
    gate = SimpleNamespace(
        get_pending=lambda session_id: pending,
        resolve=AsyncMock(return_value=pending),
    )
    monkeypatch.setattr("src.governance.router.approval_gate", gate)

    result = await resolve_approval(
        "session-1",
        ResolveApprovalRequest(approved=True),
        _user("87654321-4321-8765-4321-876543218765", role="admin"),
    )

    assert result is pending
    gate.resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_kill_switch_calls_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = SimpleNamespace(activate_kill_switch=AsyncMock())
    monkeypatch.setattr("src.governance.router.approval_gate", gate)
    admin = _user("12345678-1234-5678-1234-567812345678", role="admin")

    result = await activate_kill_switch(
        KillSwitchRequest(session_ids=["s1", "s2"], reason="operator"),
        admin,
    )

    assert result["status"] == "kill_switch_activated"
    gate.activate_kill_switch.assert_awaited_once()
