"""Real-time WebSocket channel (Ch. 8.7, Table 5.1 Dashboard Service: REST + WebSocket).

``ws://host/ws?token=<access JWT>``. Messages pushed to clients::

    {"type": "telemetry", "data": [...latest points...]}
    {"type": "alert" | "alert_update", "data": {...}}

Clients may narrow the stream: ``{"action": "subscribe", "asset_ids": ["..."]}``.
Fan-out works across API replicas because every replica subscribes to the same Redis
pub/sub channel (the stream processor publishes once).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.cache import REALTIME_CHANNEL, get_cache
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.core.metrics import websocket_connections
from app.core.security import decode_token

log = get_logger(__name__)
router = APIRouter()


@dataclass(eq=False)
class Client:
    ws: WebSocket
    scopes: list[str]
    asset_ids: set[str] = field(default_factory=set)
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=200))


class ConnectionManager:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _pump(self) -> None:
        while True:
            try:
                async for message in get_cache().subscribe(REALTIME_CHANNEL):
                    for c in list(self.clients):
                        filtered = self._filter(c, message)
                        if filtered is not None and not c.queue.full():  # slow consumers drop, never block
                            c.queue.put_nowait(filtered)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("ws_pubsub_reconnect", error=str(exc))
                await asyncio.sleep(2)

    @staticmethod
    def _filter(c: Client, message: dict[str, Any]) -> dict[str, Any] | None:
        data = message.get("data")
        if message.get("type") == "telemetry" and isinstance(data, list) and c.asset_ids:
            data = [d for d in data if d.get("asset_id") in c.asset_ids]
            return {"type": "telemetry", "data": data} if data else None
        return message


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    try:
        claims = decode_token(token or "")
        if await get_cache().exists(f"blacklist:{claims['jti']}"):
            raise AuthenticationError("revoked")
    except AuthenticationError:
        await ws.close(code=4401)
        return
    await ws.accept()
    client = Client(ws, list(claims.get("asset_scopes") or []))
    manager.clients.add(client)
    websocket_connections.inc()

    async def sender() -> None:
        while True:
            await ws.send_json(await client.queue.get())

    send_task = asyncio.create_task(sender())
    try:
        await ws.send_json({"type": "hello", "data": {"user": claims["sub"], "role": claims.get("role")}})
        while True:
            msg = await ws.receive_json()
            if msg.get("action") == "subscribe":
                client.asset_ids = {str(a) for a in msg.get("asset_ids", [])}
            elif msg.get("action") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        send_task.cancel()
        manager.clients.discard(client)
        websocket_connections.dec()
