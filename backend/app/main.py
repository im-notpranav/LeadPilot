"""FastAPI app: wiring, startup reset, real-time simulation loop."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_analytics, routes_leads, routes_pipeline, routes_reps, routes_sim, ws
from .api.deps import state
from .bus import AsyncQueueBus
from .config import load_config
from .persistence import NullPersistence, Persistence
from .runtime import Runtime

log = logging.getLogger("leadpilot")


async def run_reset(seed: int | None = None, warmup: bool = True) -> None:
    rt = state.runtime
    rt.clock.paused = True
    rt.status = "resetting"
    await state.ws.broadcast([{"type": "sim.reset", "data": {"status": "resetting"}}])
    async with state.lock:
        t0 = time.perf_counter()
        await asyncio.to_thread(rt.reset, seed, warmup)
        rt.processor.drain_outbox()
        log.info("reset done in %.1fs: %s events", time.perf_counter() - t0, len(rt.store.log))
    rt.clock.paused = not rt.cfg.simulator.autostart
    await state.ws.broadcast([{"type": "sim.reset", "data": {"status": "ready"}},
                              {"type": "sim.clock", "data": {**rt.clock.state(), "status": rt.status}}])


async def sim_loop() -> None:
    rt = state.runtime
    step = rt.cfg.simulator.real_step_ms / 1000
    last = time.monotonic()
    last_clock_push = 0.0
    while True:
        await asyncio.sleep(step)
        now_m = time.monotonic()
        dt, last = now_m - last, now_m
        if rt.status != "ready":
            continue
        msgs = []
        if not rt.clock.paused:
            target = rt.clock.target_after(dt)
            try:
                async with state.lock:
                    rt.run_until(target)
                    msgs = rt.processor.drain_outbox()
            except Exception:  # keep the loop alive; surface in logs
                log.exception("simulation step failed")
        if now_m - last_clock_push > 0.5 or msgs:
            msgs.append({"type": "sim.clock", "data": {**rt.clock.state(), "status": rt.status}})
            last_clock_push = now_m
        await state.ws.broadcast(msgs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    overrides = {}
    if os.environ.get("LEADPILOT_WARMUP_DAYS"):
        overrides = {"simulator": {"warmup_days": int(os.environ["LEADPILOT_WARMUP_DAYS"])}}
    cfg = load_config(overrides=overrides)
    persist = os.environ.get("LEADPILOT_PERSIST", "1") != "0"
    db = Persistence() if persist else NullPersistence()
    state.runtime = Runtime(cfg, db)
    state.lock = asyncio.Lock()
    state.ws = ws.ConnectionManager()
    state.bus = AsyncQueueBus(state.runtime.emit, state.lock)
    state.bus.start()
    state.reset_task = asyncio.create_task(run_reset())
    state.loop_task = asyncio.create_task(sim_loop())
    yield
    state.loop_task.cancel()
    await state.bus.stop()


app = FastAPI(title="LeadPilot", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (routes_leads.router, routes_pipeline.router, routes_reps.router, routes_analytics.router,
          routes_sim.router, ws.router):
    app.include_router(r)
