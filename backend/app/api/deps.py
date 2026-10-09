"""Shared application state for the API layer."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class AppState:
    runtime: object = None
    settings: object = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    bus: object = None
    ws: object = None
    loop_task: object = None
    reset_task: object = None


state = AppState()


def lead_or_404(lead_id: str):
    from fastapi import HTTPException
    store = state.runtime.store
    lid = store.resolve_lead_id(lead_id) if lead_id in store.leads else None
    if lid is None:
        raise HTTPException(404, f"lead {lead_id} not found")
    return store.leads[lid]


def demo_only() -> None:
    """Dependency for simulator controls: they would corrupt real data, so live mode refuses them."""
    from fastapi import HTTPException
    if state.runtime is not None and state.runtime.live:
        raise HTTPException(409, "simulator controls are disabled in live mode")
