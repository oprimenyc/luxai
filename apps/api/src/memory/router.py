"""Memory management API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.memory.models import (
    Memory,
    MemoryCreate,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryType,
)
from src.memory.service import MemoryService
from src.middleware.auth import AuthenticatedUser, get_current_user
from src.services import get_supabase_client

router = APIRouter(prefix="/memory", tags=["memory"])


async def get_memory_service() -> MemoryService:
    client = await get_supabase_client()
    return MemoryService(client)


@router.post("", response_model=Memory, status_code=status.HTTP_201_CREATED)
async def store_memory(
    payload: MemoryCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: MemoryService = Depends(get_memory_service),
) -> Memory:
    return await service.store(user_id=current_user.user_id, payload=payload)


@router.post("/search", response_model=list[MemorySearchResult])
async def search_memories(
    request: MemorySearchRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemorySearchResult]:
    return await service.search(user_id=current_user.user_id, request=request)


@router.get("", response_model=list[Memory])
async def list_memories(
    memory_type: MemoryType | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: MemoryService = Depends(get_memory_service),
) -> list[Memory]:
    memories, _ = await service.list_memories(
        user_id=current_user.user_id,
        memory_type=memory_type,
        agent_id=agent_id,
        page=page,
        page_size=page_size,
    )
    return memories


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: MemoryService = Depends(get_memory_service),
) -> None:
    deleted = await service.delete_memory(
        memory_id=memory_id,
        user_id=current_user.user_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
