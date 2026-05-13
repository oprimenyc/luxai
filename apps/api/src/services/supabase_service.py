"""Supabase service for database operations."""

from functools import lru_cache
from typing import Any
from uuid import UUID

import structlog
from supabase import AsyncClient, acreate_client

from src.config import settings

log = structlog.get_logger(__name__)


@lru_cache
def _get_supabase_client() -> AsyncClient:
    raise RuntimeError("Call get_supabase_client() as async — do not cache async clients")


async def get_supabase_client() -> AsyncClient:
    return await acreate_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key,
    )


class AgentService:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list_agents(
        self,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size
        result = (
            await self._client.table("agents")
            .select("*", count="exact")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        return result.data, result.count or 0

    async def get_agent(self, agent_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        result = (
            await self._client.table("agents")
            .select("*")
            .eq("id", str(agent_id))
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        return result.data

    async def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.table("agents").insert(data).select().single().execute()
        return result.data

    async def update_agent(
        self,
        agent_id: UUID,
        user_id: UUID,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        result = (
            await self._client.table("agents")
            .update(data)
            .eq("id", str(agent_id))
            .eq("user_id", str(user_id))
            .select()
            .single()
            .execute()
        )
        return result.data

    async def delete_agent(self, agent_id: UUID, user_id: UUID) -> bool:
        result = (
            await self._client.table("agents")
            .delete()
            .eq("id", str(agent_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(result.data)


class SessionService:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list_sessions(
        self,
        user_id: UUID,
        agent_id: UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size
        query = (
            self._client.table("sessions")
            .select("*", count="exact")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if agent_id:
            query = query.eq("agent_id", str(agent_id))
        result = await query.execute()
        return result.data, result.count or 0

    async def get_session(self, session_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        result = (
            await self._client.table("sessions")
            .select("*")
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        return result.data

    async def create_session(self, data: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.table("sessions").insert(data).select().single().execute()
        return result.data

    async def update_session(
        self,
        session_id: UUID,
        user_id: UUID,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        result = (
            await self._client.table("sessions")
            .update(data)
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .select()
            .single()
            .execute()
        )
        return result.data
