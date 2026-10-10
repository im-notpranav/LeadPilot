"""WebSocket fan-out. Messages are sent as {"type": "batch", "messages": [...]} envelopes.

Each connection is authenticated (?token=) and only receives messages about leads its principal may see.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import Principal
from .deps import state
from .security import ws_principal

router = APIRouter()

GLOBAL_PREFIXES = ("sim.", "scenario.")          # clock and simulator status: everyone
MANAGER_ONLY = {"source.flagged"}


def visible(p: Principal, msg: dict) -> bool:
    if p.sees_all:
        return True
    kind, data = msg.get("type", ""), msg.get("data") or {}
    if kind.startswith(GLOBAL_PREFIXES):
        return True
    if kind in MANAGER_ONLY:
        return p.role == "manager"
    lead_id = data.get("lead_id") or data.get("survivor_id")
    if lead_id is None:
        return False
    store = state.runtime.store
    return p.can_see(store.leads.get(store.resolve_lead_id(lead_id) or lead_id))


class ConnectionManager:
    def __init__(self):
        self.clients: dict[WebSocket, Principal] = {}

    async def connect(self, ws: WebSocket, principal: Principal) -> None:
        await ws.accept()
        self.clients[ws] = principal

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    @staticmethod
    def _envelope(messages: list[dict]) -> str:
        return json.dumps({"type": "batch", "messages": messages[-300:], "dropped": max(0, len(messages) - 300)},
                          default=str)

    async def broadcast(self, messages: list[dict]) -> None:
        if not messages or not self.clients:
            return
        shared = None
        dead = []
        for ws, p in list(self.clients.items()):
            if p.sees_all:
                shared = shared or self._envelope(messages)
                payload = shared
            else:
                mine = [m for m in messages if visible(p, m)]
                if not mine:
                    continue
                payload = self._envelope(mine)
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    principal = await ws_principal(ws)
    if principal is None:
        await ws.close(code=4401, reason="sign in required")
        return
    await state.ws.connect(ws, principal)
    try:
        await ws.send_text(json.dumps({"type": "batch", "messages": [
            {"type": "sim.clock", "data": {**state.runtime.clock.state(), "status": state.runtime.status}}]}))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.ws.disconnect(ws)
    except Exception:
        state.ws.disconnect(ws)
