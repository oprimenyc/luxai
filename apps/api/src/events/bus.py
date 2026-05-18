"""Async in-process event bus with persistence and replay support."""

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any

import structlog

from src.events.models import BaseEvent, EventType

log = structlog.get_logger(__name__)

Handler = Callable[[BaseEvent], Coroutine[Any, Any, None]]

_REPLAY_BUFFER_SIZE = 500


class EventBus:
    """
    Central async event bus.

    - pub/sub with typed handlers
    - per-session subscription channels for WebSocket fanout
    - in-memory replay ring buffer (last N events per session)
    - metrics counters
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = defaultdict(list)
        self._global_handlers: list[Handler] = []
        self._session_queues: dict[str, list[asyncio.Queue[BaseEvent]]] = defaultdict(list)
        self._global_queues: list[asyncio.Queue[BaseEvent]] = []
        self._replay_buffer: dict[str, deque[BaseEvent]] = defaultdict(
            lambda: deque(maxlen=_REPLAY_BUFFER_SIZE)
        )
        self._sequence: int = 0
        self._published_count: int = 0
        self._dropped_count: int = 0
        # Hold strong references to background tasks to prevent premature GC
        self._tasks: set[asyncio.Task[None]] = set()

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribers."""
        self._sequence += 1
        self._published_count += 1

        # Store in replay buffer
        if event.session_id:
            self._replay_buffer[event.session_id].append(event)
        self._replay_buffer["__global__"].append(event)

        # Notify typed handlers
        for handler in self._handlers.get(event.type, []):
            self._spawn(self._safe_call(handler, event))

        # Notify global handlers
        for handler in self._global_handlers:
            self._spawn(self._safe_call(handler, event))

        # Fan out to session-specific queues
        if event.session_id:
            for queue in self._session_queues.get(event.session_id, []):
                if not queue.full():
                    await queue.put(event)
                else:
                    self._dropped_count += 1
                    log.warning("event_queue_full", session_id=event.session_id)

        # Fan out to global queues
        for queue in self._global_queues:
            if not queue.full():
                await queue.put(event)
            else:
                self._dropped_count += 1

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Create a background task and hold a strong reference until completion."""
        task: asyncio.Task[None] = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register a typed event handler."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register a handler for all event types."""
        self._global_handlers.append(handler)

    def subscribe_session(
        self,
        session_id: str,
        queue: asyncio.Queue[BaseEvent],
    ) -> None:
        """Subscribe a queue to receive all events for a session."""
        self._session_queues[session_id].append(queue)

    def unsubscribe_session(
        self,
        session_id: str,
        queue: asyncio.Queue[BaseEvent],
    ) -> None:
        try:
            self._session_queues[session_id].remove(queue)
        except ValueError:
            pass

    def subscribe_global_queue(self, queue: asyncio.Queue[BaseEvent]) -> None:
        self._global_queues.append(queue)

    def unsubscribe_global_queue(self, queue: asyncio.Queue[BaseEvent]) -> None:
        try:
            self._global_queues.remove(queue)
        except ValueError:
            pass

    def get_replay_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[BaseEvent]:
        """Return recent events for replay on reconnect."""
        key = session_id or "__global__"
        buf = self._replay_buffer.get(key, deque())
        events = list(buf)
        return events[-limit:]

    async def stream_session(
        self,
        session_id: str,
        queue_size: int = 256,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Async generator that yields events for a session."""
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=queue_size)
        self.subscribe_session(session_id, queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self.unsubscribe_session(session_id, queue)

    async def stream_global(
        self,
        queue_size: int = 512,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Async generator that yields all events."""
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=queue_size)
        self.subscribe_global_queue(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self.unsubscribe_global_queue(queue)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "published": self._published_count,
            "dropped": self._dropped_count,
            "sequence": self._sequence,
            "active_sessions": len(self._session_queues),
            "pending_tasks": len(self._tasks),
        }

    @staticmethod
    async def _safe_call(handler: Handler, event: BaseEvent) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception(
                "event_handler_error",
                handler=getattr(handler, "__name__", repr(handler)),
                event_type=str(event.type),
            )


# ── Singleton ─────────────────────────────────────────────────────────────────
event_bus = EventBus()
