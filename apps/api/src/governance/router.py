"""
Governance API endpoints — RBAC, approvals, kill switch.

Path: apps/api/src/governance/router.py
Security: Approval resolution is limited to the requesting user or an admin.
          Governance kill-switch activation is admin-only. JWT role checks read
          the Supabase admin claim from app_metadata, not user-writable fields.
Scale: In-memory approval gate for single-instance runtime; revisit if the
       orchestrator becomes multi-instance.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.governance.engine import approval_gate, risk_engine
from src.governance.models import (
    ApprovalRequest,
    ApprovalStatus,
    RiskAssessment,
)
from src.middleware.auth import AuthenticatedUser, get_admin_user, get_current_user

router = APIRouter(prefix="/governance", tags=["governance"])


class AssessRiskRequest(BaseModel):
    session_id: str
    agent_id: str
    task: str
    requested_tools: list[str] = []


class ResolveApprovalRequest(BaseModel):
    approved: bool
    reason: str | None = None


class KillSwitchRequest(BaseModel):
    session_ids: list[str]
    reason: str


@router.post("/assess", response_model=RiskAssessment)
async def assess_risk(
    request: AssessRiskRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> RiskAssessment:
    return risk_engine.assess(
        session_id=request.session_id,
        agent_id=request.agent_id,
        task=request.task,
        requested_tools=request.requested_tools,
    )


@router.get("/approvals/pending", response_model=list[ApprovalRequest])
async def list_pending_approvals(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[ApprovalRequest]:
    return [
        req
        for req in approval_gate._pending.values()
        if req.user_id == str(current_user.user_id)
    ]


@router.post("/approvals/{session_id}/resolve", response_model=ApprovalRequest)
async def resolve_approval(
    session_id: str,
    request: ResolveApprovalRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ApprovalRequest:
    pending = approval_gate.get_pending(session_id)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found or expired",
        )

    if not current_user.is_admin and pending.user_id != str(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only resolve your own approval requests.",
        )

    result = await approval_gate.resolve(
        session_id=session_id,
        approved=request.approved,
        resolved_by=str(current_user.user_id),
        reason=request.reason,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found or expired",
        )
    return result


@router.post("/kill-switch", status_code=status.HTTP_200_OK)
async def activate_kill_switch(
    request: KillSwitchRequest,
    current_user: AuthenticatedUser = Depends(get_admin_user),
) -> dict:
    await approval_gate.activate_kill_switch(
        session_ids=request.session_ids,
        reason=request.reason,
        activated_by=str(current_user.user_id),
    )
    return {
        "status": "kill_switch_activated",
        "affected_sessions": request.session_ids,
    }
