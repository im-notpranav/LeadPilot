"""Simulator control, live feed, replay."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

from ..simulator.scenarios import SCENARIOS
from .deps import demo_only, state

router = APIRouter(prefix="/api")


@router.get("/sim/status")
async def status():
    return state.runtime.stats()


@router.post("/sim/start", dependencies=[Depends(demo_only)])
async def start():
    state.runtime.clock.paused = False
    return state.runtime.clock.state()


@router.post("/sim/pause", dependencies=[Depends(demo_only)])
async def pause():
    state.runtime.clock.paused = True
    return state.runtime.clock.state()


@router.post("/sim/step", dependencies=[Depends(demo_only)])
async def step(body: dict = Body(default={})):
    minutes = float(body.get("minutes", 60))
    if not 0 < minutes <= 60 * 24 * 14:
        raise HTTPException(422, "minutes must be in (0, 20160]")
    async with state.lock:
        n = state.runtime.step(minutes)
        msgs = state.runtime.processor.drain_outbox()
    await state.ws.broadcast(msgs)
    return {"processed": n, "clock": state.runtime.clock.state()}


@router.post("/sim/speed", dependencies=[Depends(demo_only)])
async def speed(body: dict = Body(...)):
    s = float(body.get("speed", 60))
    if not 0.1 <= s <= 3600:
        raise HTTPException(422, "speed out of range")
    state.runtime.clock.speed = s
    return state.runtime.clock.state()


@router.post("/sim/reset", dependencies=[Depends(demo_only)])
async def reset(body: dict = Body(default={})):
    if state.runtime.status == "resetting":
        raise HTTPException(409, "reset already in progress")
    seed = body.get("seed")
    warmup = body.get("warmup", True)
    from ..main import run_reset
    state.reset_task = asyncio.create_task(run_reset(int(seed) if seed is not None else None, bool(warmup)))
    return {"status": "resetting", "seed": seed}


@router.post("/sim/background", dependencies=[Depends(demo_only)])
async def background(body: dict = Body(...)):
    state.runtime.sim.background = bool(body.get("enabled", True))
    return {"background": state.runtime.sim.background}


@router.post("/sim/rep-actions", dependencies=[Depends(demo_only)])
async def rep_actions(body: dict = Body(...)):
    state.runtime.sim.rep_actions = bool(body.get("enabled", True))
    return {"rep_actions": state.runtime.sim.rep_actions}


@router.get("/sim/scenarios")
async def scenarios():
    runs = state.runtime.scenario_runs
    return {"items": [{"name": k, **v, "runs": runs.get(k, 0)} for k, v in SCENARIOS.items()]}


@router.post("/sim/scenario/{name}", dependencies=[Depends(demo_only)])
async def scenario(name: str):
    if name not in SCENARIOS:
        raise HTTPException(404, "unknown scenario")
    if state.runtime.status != "ready":
        raise HTTPException(409, "simulator not ready")
    async with state.lock:
        info = state.runtime.launch_scenario(name)
        msgs = state.runtime.processor.drain_outbox()
    await state.ws.broadcast(msgs + [{"type": "scenario.launched", "data": info}])
    return info


@router.get("/feed")
async def feed(type: str | None = None, limit: int = 100, lead_id: str | None = None):
    async with state.lock:
        items = list(state.runtime.store.feed)
    if type:
        types = set(type.split(","))
        items = [i for i in items if i["type"] in types]
    if lead_id:
        items = [i for i in items if i["lead_id"] == lead_id]
    return {"items": items[:limit]}


@router.post("/replay")
async def replay():
    async with state.lock:
        before = state.runtime.stats()
        result = await asyncio.to_thread(state.runtime.processor.replay)
        state.runtime.processor.drain_outbox()
    await state.ws.broadcast([{"type": "sim.reset", "data": {"reason": "replay"}}])
    return {**result, "events_before": before["events"], "leads_before": before["leads"]}


@router.get("/health")
async def health():
    rt = state.runtime
    return {"ok": True, "status": rt.status if rt else "starting", "mode": ("live" if rt.live else "demo") if rt else None,
            "db": rt.db.status() if rt else None}
