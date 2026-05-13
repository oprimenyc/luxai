"""Persist events to Supabase for replay, audit, and analytics."""

import structlog
from supabase import AsyncClient

from src.events.models import BaseEvent, EventSeverity

log = structlog.get_logger(__name__)

_MIN_SEVERITY_TO_PERSIST = {
    EventSeverity.DEBUG: 0,
    EventSeverity.INFO: 1,
    EventSeverity.WARNING: 2,
    EventSeverity.ERROR: 3,
    EventSeverity.CRITICAL: 4,
}
_PERSIST_THRESHOLD = 1  # INFO and above


class EventPersistence:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def persist(self, event: BaseEvent) -> None:
        if _MIN_SEVERITY_TO_PERSIST[event.severity] < _PERSIST_THRESHOLD:
            return

        try:
            await self._client.table("events").insert({
                "id": str(event.id),
                "type": event.type.value,
                "severity": event.severity.value,
                "timestamp": event.timestamp.isoformat(),
                "session_id": event.session_id,
                "agent_id": event.agent_id,
                "user_id": event.user_id,
                "correlation_id": event.correlation_id,
                "payload": event.payload,
                "metadata": event.metadata,
            }).execute()
        except Exception:
            log.exception("event_persist_failed", event_id=str(event.id), event_type=event.type)

    async def get_events(
        self,
        session_id: str | None = None,
        event_types: list[str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        query = (
            self._client.table("events")
            .select("*")
            .order("timestamp", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if session_id:
            query = query.eq("session_id", session_id)
        if event_types:
            query = query.in_("type", event_types)

        result = await query.execute()
        return result.data or []
