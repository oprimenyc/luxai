"""Workflow management API endpoints."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.middleware.auth import AuthenticatedUser, get_current_user
from src.services import get_supabase_client
from src.workflows.engine import WorkflowEngine
from src.workflows.models import Workflow, WorkflowCreate

router = APIRouter(prefix="/workflows", tags=["workflows"])


async def get_engine() -> WorkflowEngine:
    client = await get_supabase_client()
    return WorkflowEngine(client)


@router.post("", response_model=Workflow, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    engine: WorkflowEngine = Depends(get_engine),
) -> Workflow:
    return await engine.create(user_id=current_user.user_id, payload=payload)


@router.post("/{workflow_id}/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_workflow(
    workflow_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedUser = Depends(get_current_user),
    engine: WorkflowEngine = Depends(get_engine),
) -> dict:
    background_tasks.add_task(engine.execute, workflow_id, current_user.user_id)
    return {"status": "accepted", "workflow_id": str(workflow_id)}
