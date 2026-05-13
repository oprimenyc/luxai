"""WebSocket + SSE gateway endpoints."""

import asyncio
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket
from fastapi.responses import StreamingResponse

from src.events.bus import event_bus
from src.middleware.auth import AuthenticatedUser, get_current_user
from src.websocket.manager import ws_manager

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["realtime"])


@router.websocket("/events")
async def ws_global_events(websocket: WebSocket) -> None:
    """Global event stream — receives all events for authenticated user."""
    # Authenticate via token in query param (WebSocket limitation)
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    user_id = websocket.query_params.get("user_id", "anonymous")
    conn = await ws_manager.connect(websocket, user_id=user_id)

    # Subscribe this connection to the event bus
    async def fan_out(event) -> None:
        await ws_manager.broadcast(event)

    event_bus.subscribe_all(fan_out)

    try:
        await ws_manager.handle(conn)
    finally:
        await ws_manager.disconnect(conn.id)


@router.websocket("/sessions/{session_id}")
async def ws_session_events(
    websocket: WebSocket,
    session_id: str,
) -> None:
    """Session-scoped event stream."""
    user_id = websocket.query_params.get("user_id", "anonymous")
    conn = await ws_manager.connect(websocket, user_id=user_id, session_id=session_id)

    async def fan_out(event) -> None:
        if event.session_id == session_id:
            await ws_manager.broadcast(event)

    event_bus.subscribe_all(fan_out)

    try:
        await ws_manager.handle(conn)
    finally:
        await ws_manager.disconnect(conn.id)


@router.get("/sse/events")
async def sse_global_events(
    current_user: AuthenticatedUser = Depends(get_current_user),
    last_event_id: str | None = Query(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """SSE fallback for environments that don't support WebSocket."""

    async def generate() -> AsyncGenerator[str, None]:
        # Replay missed events if Last-Event-ID provided
        if last_event_id:
            replay = event_bus.get_replay_events(limit=100)
            for ev in replay:
                if str(ev.id) == last_event_id:
                    break
                yield f"id: {ev.id}\ndata: {ev.model_dump_json()}\n\n"

        # Stream new events
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        event_bus.subscribe_global_queue(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe_global_queue(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sse/sessions/{session_id}")
async def sse_session_events(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse:
    async def generate() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        event_bus.subscribe_session(session_id, queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe_session(session_id, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
