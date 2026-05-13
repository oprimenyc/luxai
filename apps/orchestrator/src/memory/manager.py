"""Memory manager — integrates with the LuxAI memory API during graph execution."""

import httpx
import structlog

from src.config import settings

log = structlog.get_logger(__name__)

_API_BASE = settings.orchestrator_url.replace("8001", "8000")  # Point to API service


class MemoryManager:
    """
    Called by graph nodes to store and retrieve memories during execution.
    Communicates with the FastAPI memory service.
    """

    def __init__(self, user_id: str, session_id: str, auth_token: str = "") -> None:
        self.user_id = user_id
        self.session_id = session_id
        self._headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    async def store(
        self,
        content: str,
        memory_type: str = "episodic",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> str | None:
        """Store a memory and return its ID."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_API_BASE}/api/v1/memory",
                    json={
                        "content": content,
                        "memory_type": memory_type,
                        "session_id": self.session_id,
                        "importance_score": importance,
                        "tags": tags or [],
                    },
                    headers=self._headers,
                )
                if resp.status_code == 201:
                    return resp.json().get("id")
        except Exception as exc:
            log.warning("memory_store_failed", error=str(exc))
        return None

    async def recall(
        self,
        query: str,
        memory_types: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Retrieve relevant memories for a query."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_API_BASE}/api/v1/memory/search",
                    json={
                        "query": query,
                        "memory_types": memory_types,
                        "session_id": self.session_id,
                        "limit": limit,
                        "min_similarity": 0.65,
                    },
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return [r["memory"] for r in resp.json()]
        except Exception as exc:
            log.warning("memory_recall_failed", error=str(exc))
        return []

    def format_memories_for_context(self, memories: list[dict]) -> str:
        """Format retrieved memories as a context string for prompts."""
        if not memories:
            return ""
        parts = ["[Relevant memories from previous interactions:]"]
        for i, mem in enumerate(memories, 1):
            parts.append(f"{i}. ({mem.get('memory_type', 'unknown')}) {mem.get('content', '')[:300]}")
        return "\n".join(parts)
