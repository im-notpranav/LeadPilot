"""Reps with live load and metrics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..analytics.rep_performance import rep_performance
from ..auth import Principal
from .deps import state
from .security import user

router = APIRouter(prefix="/api")


@router.get("/reps")
async def reps(p: Principal = Depends(user)):
    async with state.lock:
        rt = state.runtime
        return {"items": [r for r in rep_performance(rt.store, rt.cfg, rt.clock.now()) if p.can_see_rep(r["rep_id"])]}


@router.get("/reps/{rep_id}")
async def rep(rep_id: str, p: Principal = Depends(user)):
    if not p.can_see_rep(rep_id):
        raise HTTPException(404, "rep not found")
    async with state.lock:
        rt = state.runtime
        perf = {r["rep_id"]: r for r in rep_performance(rt.store, rt.cfg, rt.clock.now())}
        if rep_id not in perf:
            raise HTTPException(404, "rep not found")
        store = rt.store
        leads = [store.lead_view(store.leads[x]) for x in sorted(store.owner_index.get(rep_id, ()))
                 if store.leads[x].ev is not None]
        return {**perf[rep_id], "leads": sorted(leads, key=lambda v: -v["priority"])}
