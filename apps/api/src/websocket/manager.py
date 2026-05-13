"""WebSocket connection manager with multiplexing and heartbeats."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from src.events.bus import event_bus
from src.events.models import BaseEvent

log = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL = 15  # seconds
MAX_CONNECTIONS_PER_USER = 10


@dataclass
class Connection:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    websocket: WebSocket = field(repr=False)
    user_id: str = ""
    session_id: str | None = None
    subscriptions: set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=lambda: __import__("time").time())
    message_count: int = 0


class WebSocketManager:
    """
    Manages all active WebSocket connections.

    - Per-user connection tracking
    - Session-scoped subscription fanout
    - Heartbeat loop
    - JSON serialization with error isolation
    """

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}  # conn_id → Connection
        self._user_connections: dict[str, set[str]] = {}  # user_id → {conn_ids}
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        session_id: str | None = None,
    ) -> Connection:
        await websocket.accept()

        user_conn_count = len(self._user_connections.get(user_id, set()))
        if user_conn_count >= MAX_CONNECTIONS_PER_USER:
            await websocket.close(code=1008, reason="Max connections exceeded")
            raise RuntimeError("Max connections exceeded for user")

        conn = Connection(websocket=websocket, user_id=user_id, session_id=session_id)
        self._connections[conn.id] = conn
        self._user_connections.setdefault(user_id, set()).add(conn.id)

        # Replay recent events
        replay = event_bus.get_replay_events(session_id=session_id, limit=50)
        for event in replay:
            await self._send(conn, event, replay=True)

        log.info(
            "ws_connected",
            conn_id=conn.id,
            user_id=user_id,
            session_id=session_id,
            total=len(self._connections),
        )
        return conn

    async def disconnect(self, conn_id: str) -> None:
        conn = self._connections.pop(conn_id, None)
        if conn:
            self._user_connections.get(conn.user_id, set()).discard(conn_id)
            log.info("ws_disconnected", conn_id=conn_id, total=len(self._connections))

    async def broadcast(self, event: BaseEvent) -> None:
        """Broadcast an event to all relevant connections."""
        dead: list[str] = []
        for conn_id, conn in self._connections.items():
            # Only send to connections interested in this event
            if conn.session_id and conn.session_id != event.session_id:
                continue
            if conn.user_id and event.user_id and conn.user_id != event.user_id:
                if not conn.session_id:  # global monitors receive everything
                    continue
            try:
                await self._send(conn, event)
            except Exception:
                dead.append(conn_id)

        for conn_id in dead:
            await self.disconnect(conn_id)

    async def send_to_user(self, user_id: str, data: dict[str, Any]) -> None:
        for conn_id in list(self._user_connections.get(user_id, set())):
            conn = self._connections.get(conn_id)
            if conn:
                try:
                    await conn.websocket.send_json(data)
                    conn.message_count += 1
                except Exception:
                    await self.disconnect(conn_id)

    async def handle(self, conn: Connection) -> None:
        """Main message loop for a connection."""
        try:
            while True:
                data = await conn.websocket.receive_json()
                await self._handle_client_message(conn, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws_handle_error", conn_id=conn.id)
        finally:
            await self.disconnect(conn.id)

    async def _handle_client_message(
        self,
        conn: Connection,
        data: dict[str, Any],
    ) -> None:
        msg_type = data.get("type")
        if msg_type == "subscribe":
            conn.subscriptions.add(data.get("channel", ""))
        elif msg_type == "unsubscribe":
            conn.subscriptions.discard(data.get("channel", ""))
        elif msg_type == "ping":
            await conn.websocket.send_json({"type": "pong", "ts": data.get("ts")})

    async def _send(self, conn: Connection, event: BaseEvent, replay: bool = False) -> None:
        payload = {
            "type": "event",
            "replay": replay,
            "event": json.loads(event.model_dump_json()),
        }
        await conn.websocket.send_json(payload)
        conn.message_count += 1

    def start_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            dead: list[str] = []
            for conn_id, conn in self._connections.items():
                try:
                    await conn.websocket.send_json({
                        "type": "heartbeat",
                        "connections": len(self._connections),
                    })
                except Exception:
                    dead.append(conn_id)
            for conn_id in dead:
                await self.disconnect(conn_id)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_connections": len(self._connections),
            "unique_users": len(self._user_connections),
        }


ws_manager = WebSocketManager()
