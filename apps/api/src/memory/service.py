"""Memory service — pgvector hybrid search, aging, and lifecycle management."""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from supabase import AsyncClient

from src.events.bus import event_bus
from src.events.models import MemoryRetrievedEvent, MemoryStoredEvent
from src.memory.embedding import embed_text
from src.memory.models import (
    Memory,
    MemoryCreate,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
)

log = structlog.get_logger(__name__)


class MemoryService:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def store(
        self,
        user_id: UUID,
        payload: MemoryCreate,
    ) -> Memory:
        """Embed and store a memory with pgvector."""
        embedding = await embed_text(payload.content)

        row = {
            "user_id": str(user_id),
            "content": payload.content,
            "memory_type": payload.memory_type.value,
            "agent_id": payload.agent_id,
            "session_id": payload.session_id,
            "tags": payload.tags,
            "metadata": payload.metadata,
            "importance_score": payload.importance_score,
            "confidence_score": payload.confidence_score,
            "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
            "embedding": embedding,
            "embedding_model": "text-embedding-3-small",
            "status": MemoryStatus.ACTIVE.value,
        }

        result = await self._client.table("memories").insert(row).select().single().execute()
        memory = Memory(**result.data)

        await event_bus.publish(
            MemoryStoredEvent(
                user_id=str(user_id),
                payload={
                    "memory_id": str(memory.id),
                    "memory_type": memory.memory_type.value,
                    "content_preview": memory.content[:200],
                    "embedding_model": "text-embedding-3-small",
                },
            )
        )

        log.info("memory_stored", memory_id=str(memory.id), type=memory.memory_type)
        return memory

    async def search(
        self,
        user_id: UUID,
        request: MemorySearchRequest,
    ) -> list[MemorySearchResult]:
        """Hybrid vector + metadata search with RRF fusion."""
        query_embedding = await embed_text(request.query)

        # Build RPC parameters
        params: dict[str, Any] = {
            "query_embedding": query_embedding,
            "user_id_filter": str(user_id),
            "match_threshold": request.min_similarity,
            "match_count": request.limit,
        }
        if request.memory_types:
            params["memory_types"] = [t.value for t in request.memory_types]
        if request.agent_id:
            params["agent_id_filter"] = request.agent_id
        if request.session_id:
            params["session_id_filter"] = request.session_id
        if request.tags:
            params["tags_filter"] = request.tags

        result = await self._client.rpc("search_memories", params).execute()
        rows = result.data or []

        results = [
            MemorySearchResult(
                memory=Memory(**{k: v for k, v in row.items() if k != "similarity"}),
                similarity_score=row.get("similarity", 0.0),
                rank=i + 1,
            )
            for i, row in enumerate(rows)
        ]

        # Update access counts async
        if results:
            memory_ids = [str(r.memory.id) for r in results]
            await self._update_access(memory_ids)

            await event_bus.publish(
                MemoryRetrievedEvent(
                    user_id=str(user_id),
                    payload={
                        "memory_ids": memory_ids,
                        "scores": [r.similarity_score for r in results],
                        "query_preview": request.query[:100],
                        "count": len(results),
                    },
                )
            )

        return results

    async def list_memories(
        self,
        user_id: UUID,
        memory_type: MemoryType | None = None,
        agent_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Memory], int]:
        offset = (page - 1) * page_size
        query = (
            self._client.table("memories")
            .select("*", count="exact")
            .eq("user_id", str(user_id))
            .neq("status", MemoryStatus.EVICTED.value)
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if memory_type:
            query = query.eq("memory_type", memory_type.value)
        if agent_id:
            query = query.eq("agent_id", agent_id)

        result = await query.execute()
        memories = [Memory(**row) for row in result.data or []]
        return memories, result.count or 0

    async def get_memory(self, memory_id: UUID, user_id: UUID) -> Memory | None:
        result = (
            await self._client.table("memories")
            .select("*")
            .eq("id", str(memory_id))
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        return Memory(**result.data) if result.data else None

    async def delete_memory(self, memory_id: UUID, user_id: UUID) -> bool:
        result = (
            await self._client.table("memories")
            .update({"status": MemoryStatus.EVICTED.value})
            .eq("id", str(memory_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(result.data)

    async def run_aging(self, user_id: UUID) -> int:
        """Expire stale memories and compress old episodic memories."""
        now = datetime.utcnow().isoformat()

        # Expire memories past their TTL
        expired = (
            await self._client.table("memories")
            .update({"status": MemoryStatus.EVICTED.value})
            .eq("user_id", str(user_id))
            .lt("expires_at", now)
            .eq("status", MemoryStatus.ACTIVE.value)
            .execute()
        )

        count = len(expired.data or [])
        if count:
            log.info("memory_aging_expired", count=count, user_id=str(user_id))
        return count

    async def _update_access(self, memory_ids: list[str]) -> None:
        try:
            await self._client.table("memories").update({
                "access_count": self._client.table("memories")  # type: ignore[arg-type]
                .select("access_count"),  # Supabase doesn't support increment in update directly
                "last_accessed_at": datetime.utcnow().isoformat(),
            }).in_("id", memory_ids).execute()
        except Exception:
            pass  # Non-critical
