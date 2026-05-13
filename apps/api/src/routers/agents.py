"""Agent management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.middleware.auth import AuthenticatedUser, get_current_user
from src.models.agent import Agent, AgentCreate, AgentListResponse, AgentUpdate
from src.services import AgentService, get_supabase_client

router = APIRouter(prefix="/agents", tags=["agents"])


async def get_agent_service() -> AgentService:
    client = await get_supabase_client()
    return AgentService(client)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentListResponse:
    agents_data, total = await service.list_agents(
        user_id=current_user.user_id,
        page=page,
        page_size=page_size,
    )
    agents = [Agent(**a) for a in agents_data]
    return AgentListResponse(
        agents=agents,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("", response_model=Agent, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    data = payload.model_dump()
    data["user_id"] = str(current_user.user_id)
    data["capabilities"] = [c.value for c in payload.capabilities]
    result = await service.create_agent(data)
    return Agent(**result)


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(
    agent_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    result = await service.get_agent(agent_id=agent_id, user_id=current_user.user_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return Agent(**result)


@router.patch("/{agent_id}", response_model=Agent)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await service.update_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
        data=data,
    )
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return Agent(**result)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> None:
    deleted = await service.delete_agent(agent_id=agent_id, user_id=current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
