"""Runtime: wires Clock + Scheduler + Simulator + Processor.

Demo mode owns reset (simulated history + warm-up) on a SimClock. Live mode runs on the wall clock with the
simulator off, and on startup rebuilds every projection from the durable raw event log.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .clock import SimClock, WallClock
from .engine.types import iso, parse_ts
from .persistence import NullPersistence
from .processor import Processor
from .scheduler import Scheduler
from .simulator import scenarios
from .simulator.generator import Simulator
from .simulator.history import generate_history
from .store import Store


class ModeMismatch(RuntimeError):
    """The database holds data from the other run mode (demo would wipe live data; live would treat simulated
    events as real)."""


class Runtime:
    def __init__(self, cfg, persistence=None, live: bool = False):
        self.cfg = cfg
        sc = cfg.simulator
        self.live = live
        self.db = persistence or NullPersistence()
        self.clock = WallClock() if live else SimClock(sc.start_time, speed=sc.default_speed, paused=True)
        self.store = Store(cfg)
        self.processor = Processor(cfg, self.store, self.clock, self.db)
        self.scheduler = Scheduler()
        self.sim = Simulator(cfg, self.store, self.scheduler)
        self.processor.hooks.append(self._on_hook)
        self.tick_minutes = sc.tick_minutes
        self.seed = sc.seed
        self.scenario_runs: dict[str, int] = {}
        self.status = "idle"
        self.started_at: datetime | None = None

    # ------------------------------------------------------------------ lifecycle
    def ensure_mode(self, allow_switch: bool = False) -> None:
        mode, stored = ("live" if self.live else "demo"), self.db.get_meta("mode")
        if stored and stored != mode and not allow_switch:
            raise ModeMismatch(
                f"This database holds {stored}-mode data, so LeadPilot will not start in {mode} mode "
                f"({'demo resets wipe every table' if mode == 'demo' else 'simulated events would count as real'}). "
                "Point LEADPILOT_DB_SCHEMA (or LEADPILOT_DB_URL) at a separate database for each mode, "
                "or set LEADPILOT_ALLOW_MODE_SWITCH=1 if this is intended.")

    def reset(self, seed: int | None = None, warmup: bool = True, background: bool = True,
              rep_actions: bool | None = None, start: datetime | str | None = None) -> dict:
        sc = self.cfg.simulator
        self.status = "resetting"
        self.seed = sc.seed if seed is None else seed
        start_dt = parse_ts(start or sc.start_time)
        self.store.reset_all()
        self.db.reset()
        self.scheduler.clear()
        self.scenario_runs = {}
        self.sim.reset(self.seed)
        self.sim.background = background
        self.sim.rep_actions = bool(sc.rep_actions if rep_actions is None else rep_actions)
        hist = generate_history(self.cfg, random.Random(f"history-{self.seed}"), start_dt)
        self.store.historical = hist
        self.store.load_history(hist)
        for d in hist:
            self.db.add("historical_deals", d)
        for r in self.cfg.data.reps:
            self.db.upsert("reps", {k: r.get(k) for k in ("rep_id", "name", "territories", "industries", "segments",
                                                           "languages", "capacity_points", "active", "profile")})
        for s in self.cfg.data.sources:
            self.db.upsert("sources", dict(s))
        self.db.set_meta("projection_config", self.cfg.fingerprint)
        self.db.set_meta("mode", "demo")
        self.db.flush()

        t0 = start_dt - timedelta(days=sc.warmup_days) if warmup else start_dt
        self.clock.reset(t0)
        self.sim.bootstrap(t0)
        if warmup:
            self.tick_minutes = sc.warmup_tick_minutes
            self._schedule_next_tick(t0)
            proc = self.processor
            proc.broadcast, proc.autoflush = False, False
            try:
                self.run_until(start_dt, flush_every=400)
            finally:
                proc.broadcast, proc.autoflush = True, True
                self.db.flush()
            self.scheduler_drop_kind("tick")
        self.tick_minutes = sc.tick_minutes
        self.clock.reset(start_dt)
        self._schedule_next_tick(start_dt)
        self.processor.handle({"event_id": f"tick_{start_dt:%Y%m%d%H%M}_init", "type": "time_tick", "ts": iso(start_dt),
                               "actor": "system"})
        self.processor.drain_outbox()
        self.started_at = start_dt
        self.status = "ready"
        return self.stats()

    def rebuild(self) -> dict:
        """Live startup: load seed tables and closed-deal history, then replay the raw event log."""
        self.status = "resetting"
        self.store.reset_all()
        self.scheduler.clear()
        self.scenario_runs = {}
        self.sim.background, self.sim.rep_actions = False, False
        for r in self.cfg.data.reps:
            self.db.upsert("reps", {k: r.get(k) for k in ("rep_id", "name", "territories", "industries", "segments",
                                                           "languages", "capacity_points", "active", "profile")})
        for s in self.cfg.data.sources:
            self.db.upsert("sources", dict(s))
        self.db.set_meta("mode", "live")
        self.db.flush()
        self.store.historical = self.db.load_historical()   # replay's reset_projections folds it into rep stats
        self.store.raw_log = self.db.load_raw_events()
        self.processor.restore_api_seq()
        # Projections are committed in the same batch as their raw events, so they are current unless the
        # rules changed since they were written: only then rewrite them.
        rewrite = self.db.get_meta("projection_config") != self.cfg.fingerprint
        result = self.processor.replay(write=rewrite)
        now = self.clock.now()
        for lead in self.store.leads.values():      # replay runs with hooks off: re-arm pending first-touch SLAs
            if lead.first_touch_deadline is not None and lead.status == "active":
                self._on_hook("sla_deadline", lead_id=lead.lead_id, deadline=lead.first_touch_deadline)
        self._schedule_next_tick(now)
        self.started_at = now
        self.status = "ready"
        return {**self.stats(), **result}

    def apply_config(self, cfg, version: int | None = None, replay: bool = True) -> dict:
        """Switch every part of the engine to `cfg` (a settings version) and, by default, rebuild every
        projection from the raw event log under it. Blocking: run it in a thread, under the API lock."""
        from .engine import intent
        from .engine.enrich import MockEnrichmentProvider
        self.cfg = cfg
        self.store.cfg = cfg
        self.sim.cfg = cfg
        self.processor.cfg = cfg
        self.processor.config_version = version
        if isinstance(self.processor.provider, MockEnrichmentProvider):
            self.processor.provider = MockEnrichmentProvider(cfg)
        intent._CLASS_CACHE.clear()            # keyed by object id, which a new config may reuse
        if not replay:
            return {}
        self.status = "resetting"
        try:
            result = self.processor.replay(write=True)
            self.scheduler_drop_kind("sla_check")
            for lead in self.store.leads.values():  # replay runs with hooks off: re-arm pending first-touch SLAs
                if lead.first_touch_deadline is not None and lead.status == "active":
                    self._on_hook("sla_deadline", lead_id=lead.lead_id, deadline=lead.first_touch_deadline)
        finally:
            self.status = "ready"
        return result

    def scheduler_drop_kind(self, kind: str) -> None:
        import heapq
        self.scheduler._heap = [i for i in self.scheduler._heap if i.kind != kind]
        heapq.heapify(self.scheduler._heap)

    def _schedule_next_tick(self, after: datetime) -> None:
        step = timedelta(minutes=self.tick_minutes)
        epoch = after.replace(hour=0, minute=0, second=0, microsecond=0)
        n = int((after - epoch) / step) + 1
        self.scheduler.schedule(epoch + n * step, "tick")

    # ------------------------------------------------------------------ stepping
    def run_until(self, target: datetime, flush_every: int | None = None, max_items: int | None = None) -> int:
        done = 0
        while True:
            ts = self.scheduler.peek_ts()
            if ts is None or ts > target:
                break
            item = self.scheduler.pop()
            if item.ts > self.clock.now():
                self.clock.set(item.ts)
            self._dispatch(item)
            done += 1
            if flush_every and done % flush_every == 0:
                self.db.flush()
            if max_items and done >= max_items:
                return done
        self.clock.set(target)
        return done

    def step(self, minutes: float) -> int:
        return self.run_until(self.clock.now() + timedelta(minutes=minutes))

    def _dispatch(self, item) -> None:
        now = self.clock.now()
        if item.kind == "tick":
            self.processor.handle({"event_id": f"tick_{item.ts:%Y%m%d%H%M}", "type": "time_tick", "ts": iso(item.ts),
                                   "actor": "system"})
            self._schedule_next_tick(item.ts)
        elif item.kind == "sla_check":
            self.processor.handle({"event_id": f"sla_{item.data}_{item.ts:%Y%m%d%H%M%S}_{item.seq}",
                                   "type": "sla_check", "ts": iso(max(item.ts, now)), "actor": "system",
                                   "payload": {"lead_id": item.data}})
        elif item.kind == "sim":
            for ev in self.sim.fire(item.data, max(item.ts, now)):
                self.emit(ev)
        elif item.kind == "scenario":
            self.emit(item.data)

    def emit(self, event: dict) -> dict:
        return self.processor.handle(event)

    def schedule_event(self, ts: datetime, event: dict) -> None:
        self.scheduler.schedule(ts, "scenario", event)

    def launch_scenario(self, name: str) -> dict:
        return scenarios.launch(self, name)

    # ------------------------------------------------------------------ hooks
    def _on_hook(self, kind: str, **data) -> None:
        if kind == "sla_deadline":
            self.scheduler.schedule(data["deadline"] + timedelta(minutes=1), "sla_check", data["lead_id"])
        if not self.live:
            self.sim.on_hook(kind, **data)

    # ------------------------------------------------------------------ introspection
    def stats(self) -> dict:
        st = self.store
        leads = [l for l in st.leads.values() if l.ev is not None and l.status != "merged"]
        open_leads = [l for l in leads if st.is_open(l)]
        return {
            "status": self.status, "mode": "live" if self.live else "demo", "seed": self.seed, "clock": self.clock.state(),
            "events": len(st.log), "raw_events": len(st.raw_log), "leads": len(leads), "open_leads": len(open_leads),
            "stalled": sum(1 for l in open_leads if l.is_stalled), "quarantined": sum(1 for l in leads if l.status == "quarantined"),
            "merged": sum(1 for l in st.leads.values() if l.status == "merged"),
            "won": sum(1 for l in leads if l.stage == "won"), "lost": sum(1 for l in leads if l.stage == "lost"),
            "scheduled": len(self.scheduler), "latency": st.latency_stats(),
            "background": self.sim.background, "rep_actions": self.sim.rep_actions,
            "historical_deals": len(st.historical), "sim_counts": dict(self.sim.counts.most_common(12)),
            "config_version": self.processor.config_version,
        }
