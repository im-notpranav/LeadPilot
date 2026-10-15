"""FastAPI app: wiring, startup (demo reset or live rebuild), real-time processing loop."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (routes_analytics, routes_auth, routes_calls, routes_config, routes_connectors, routes_deals,
                  routes_leads, routes_notifications, routes_pipeline, routes_quotes, routes_reps, routes_sim, ws)
from .api.security import manager, user
from .auth import AccountStore, TokenVerifier
from .analytics.calibration import train_model
from .api.deps import state
from .bus import AsyncQueueBus
from .config_versions import ConfigStore
from .connectors.store import ConnectorStore
from .persistence import NullPersistence, Persistence
from .runtime import Runtime
from .calls.center import CallCenter
from .calls.storage import RecordingStore
from .notifications import NotificationCenter
from .whatif import WhatIfRuns
from .settings import get_settings

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
        state.notifications.reset()                 # the reset wiped their tables with the demo data
        state.calls.reset()
        log.info("reset done in %.1fs: %s events", time.perf_counter() - t0, len(rt.store.log))
    rt.clock.paused = not rt.cfg.simulator.autostart
    await state.ws.broadcast([{"type": "sim.reset", "data": {"status": "ready"}},
                              {"type": "sim.clock", "data": {**rt.clock.state(), "status": rt.status}}])
    await asyncio.to_thread(train_model, rt.store)   # warm the calibration model so Analytics opens instantly


async def run_rebuild() -> None:
    rt = state.runtime
    async with state.lock:
        t0 = time.perf_counter()
        result = await asyncio.to_thread(rt.rebuild)
        rt.processor.drain_outbox()
        log.info("live rebuild done in %.1fs: %s raw events, %s leads", time.perf_counter() - t0,
                 result["replayed_events"], result["leads"])
    await state.ws.broadcast([{"type": "sim.reset", "data": {"status": "ready"}},
                              {"type": "sim.clock", "data": {**rt.clock.state(), "status": rt.status}}])
    await asyncio.to_thread(train_model, rt.store)


async def publish_call_events(events: list[dict]) -> list[dict]:
    """Calls become events through the same bus as every other source."""
    from .api.routes_connectors import publish
    return await publish(events, "calls")


async def connector_flush_loop(every: float = 2.0) -> None:
    """Write connector deliveries, visitor state and counters in the background (see ConnectorStore)."""
    while True:
        await asyncio.sleep(every)
        try:
            await asyncio.to_thread(state.connectors.flush)
        except Exception:  # noqa: BLE001 - keep flushing
            log.exception("connector flush failed")


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
        else:
            msgs = rt.processor.drain_outbox()          # API events and actions while paused: push them now
        if now_m - last_clock_push > 0.5 or msgs:
            msgs.append({"type": "sim.clock", "data": {**rt.clock.state(), "status": rt.status}})
            last_clock_push = now_m
        await state.ws.broadcast(msgs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    overrides = {"simulator": {"warmup_days": settings.warmup_days}} if settings.warmup_days is not None else {}
    db = Persistence(settings.db_url, schema=settings.db_schema) if settings.persist else NullPersistence()
    # The rules in force: the YAML files plus the active settings version (version 1 = the files as they are).
    state.config = ConfigStore(db, base_overrides=overrides)
    active = state.config.ensure_initial()
    state.whatif = WhatIfRuns()
    cfg = state.config.build(active["overrides"])
    state.settings = settings
    state.accounts = AccountStore(db, settings.admin_emails)
    state.connectors = ConnectorStore(db)
    state.verifier = TokenVerifier(settings.supabase_url, settings.jwt_secret) if settings.auth else None
    if not settings.auth:
        log.warning("authentication is OFF: every request is treated as an admin")
    elif not settings.admin_emails:
        log.warning("auth is on but LEADPILOT_ADMIN_EMAILS is empty: new sign-ups stay pending until an admin exists")
    state.runtime = Runtime(cfg, db, live=settings.live)
    state.runtime.apply_config(cfg, active["id"], replay=False)
    state.runtime.ensure_mode(settings.allow_mode_switch)
    state.notifications = NotificationCenter(db, state.accounts, live=settings.live)
    state.notifications.attach(state.runtime)
    state.calls = CallCenter(db, recordings=RecordingStore(settings.supabase_url))
    state.lock = asyncio.Lock()
    state.ws = ws.ConnectionManager()
    state.bus = AsyncQueueBus(state.runtime.emit, state.lock)
    state.bus.start()
    state.calls.attach(state.runtime, publish_call_events, settings.live)
    state.reset_task = asyncio.create_task(run_rebuild() if settings.live else run_reset())
    state.loop_task = asyncio.create_task(sim_loop())
    flush_task = asyncio.create_task(connector_flush_loop())
    notify_task = asyncio.create_task(state.notifications.run())
    calls_task = asyncio.create_task(state.calls.run())
    yield
    state.loop_task.cancel()
    flush_task.cancel()
    notify_task.cancel()
    calls_task.cancel()
    await asyncio.to_thread(state.connectors.flush)
    await state.bus.stop()
    await asyncio.to_thread(db.close)          # commit everything still queued before exit


app = FastAPI(title="LeadPilot", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Public: health + auth config, connector hooks / tracker (they check the connector's own secret), and the buyer's
# quote link (/api/public/quotes/<token>: the token is the secret).
# Self: /api/me (pending users too). Admin: people, API keys, connectors. Managers: CSV import.
for r in (routes_auth.public, routes_auth.me_router, routes_auth.admin_router, routes_leads.ingest_router, ws.router,
          routes_connectors.public, routes_connectors.admin_router, routes_connectors.import_router,
          routes_quotes.public):
    app.include_router(r)
for r in (routes_leads.router, routes_pipeline.router, routes_deals.router, routes_reps.router, routes_sim.router,
          routes_notifications.router, routes_calls.router, routes_quotes.router):
    app.include_router(r, dependencies=[Depends(user)])
app.include_router(routes_analytics.router, dependencies=[Depends(manager)])
app.include_router(routes_config.router)         # managers read; admins change (checked per route)
