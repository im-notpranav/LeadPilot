"""Reps with live load and metrics."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..analytics.rep_performance import rep_performance
from .deps import state

router = APIRouter(prefix="/api")


@router.get("/reps")
async def reps():
    async with state.lock:
        rt = state.runtime
        return {"items": rep_performance(rt.store, rt.cfg, rt.clock.now())}


@router.get("/reps/{rep_id}")
async def rep(rep_id: str):
    async with state.lock:
        rt = state.runtime
        perf = {r["rep_id"]: r for r in rep_performance(rt.store, rt.cfg, rt.clock.now())}
        if rep_id not in perf:
            raise HTTPException(404, "rep not found")
        store = rt.store
        leads = [store.lead_view(store.leads[x]) for x in sorted(store.owner_index.get(rep_id, ()))
                 if store.leads[x].ev is not None]
        return {**perf[rep_id], "leads": sorted(leads, key=lambda v: -v["priority"])}
