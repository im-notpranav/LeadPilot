"""WebSocket fan-out. Messages are sent as {"type": "batch", "messages": [...]} envelopes."""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .deps import state

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, messages: list[dict]) -> None:
        if not messages or not self.clients:
            return
        payload = json.dumps({"type": "batch", "messages": messages[-300:], "dropped": max(0, len(messages) - 300)},
                             default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    await state.ws.connect(ws)
    try:
        await ws.send_text(json.dumps({"type": "batch", "messages": [
            {"type": "sim.clock", "data": {**state.runtime.clock.state(), "status": state.runtime.status}}]}))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.ws.disconnect(ws)
    except Exception:
        state.ws.disconnect(ws)
