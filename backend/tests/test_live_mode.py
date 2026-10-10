"""Live mode: wall clock, no simulator, and a durable raw event log that rebuilds every projection on restart."""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.config import load_config
from app.engine.types import iso
from app.persistence import Persistence
from app.runtime import Runtime
from test_invariants import assignments, snapshot

FAST = {"simulator": {"warmup_days": 2}}


def live_events(now: datetime) -> list[dict]:
    t = lambda h: iso(now - timedelta(hours=h))  # noqa: E731
    ref = {"email": "priya.nair@finnova.sg"}
    return [
        {"event_id": "w-1", "type": "lead_created", "ts": t(30), "source": "website",
         "payload": {"name": "Priya Nair", "email": "priya.nair@finnova.sg", "company": "FinNova Payments",
                     "title": "Head of Operations", "country": "SG", "capture_method": "form_submit",
                     "ip": "112.10.0.1", "form_fill_seconds": 25}},
        {"event_id": "w-2", "type": "page_view", "ts": t(29), "lead_ref": ref,
         "payload": {"url": "/pricing", "page_category": "pricing"}},
        {"type": "demo_request", "ts": t(28), "lead_ref": ref, "payload": {}},       # no id: gets api_0000001
        {"event_id": "w-4", "type": "email_replied", "ts": t(5), "lead_ref": ref,
         "payload": {"body": "Yes, Thursday works for a call."}},
    ]


def live_runtime(url: str) -> Runtime:
    rt = Runtime(load_config(), Persistence(url), live=True)
    rt.rebuild()
    return rt


def test_live_runtime_uses_wall_clock_and_no_simulator(tmp_path):
    rt = live_runtime(f"sqlite:///{tmp_path / 'lp.db'}")
    assert rt.status == "ready" and rt.stats()["mode"] == "live" and rt.stats()["leads"] == 0
    assert abs((rt.clock.now() - datetime.now(timezone.utc)).total_seconds()) < 5
    for e in live_events(rt.clock.now()):
        assert rt.emit(e)["status"] == "processed"
    rt.run_until(rt.clock.now())
    assert rt.scheduler.pending("sim") == 0           # simulator hooks never fire in live mode
    assert rt.scheduler.pending("tick") == 1


def test_restart_rebuilds_identical_state_from_raw_log(tmp_path):
    url = f"sqlite:///{tmp_path / 'lp.db'}"
    first = live_runtime(url)
    for e in live_events(first.clock.now()):
        first.emit(e)
    before, before_assign = snapshot(first), assignments(first)
    assert first.db.count("raw_events") == 4

    second = live_runtime(url)                         # a server restart against the same database
    assert snapshot(second) == before and assignments(second) == before_assign
    assert [r["event_id"] for r in second.store.raw_log] == ["w-1", "w-2", "api_0000001", "w-4"]
    res = second.emit({"type": "page_view", "lead_ref": {"email": "priya.nair@finnova.sg"},
                       "payload": {"page_category": "blog"}})
    assert res["status"] == "processed" and res["event_id"] == "api_0000002"   # generated ids never repeat
    assert second.db.count("raw_events") == 5


def test_demo_world_rebuilds_in_live_mode_and_replay_keeps_raw_log(tmp_path):
    url = f"sqlite:///{tmp_path / 'lp.db'}"
    demo = Runtime(load_config(overrides=FAST), Persistence(url))
    demo.reset(seed=11)
    demo.launch_scenario("reviver")
    demo.run_until(demo.clock.now() + timedelta(hours=6))
    demo.db.flush()
    raw_n = demo.db.count("raw_events")
    assert raw_n == len(demo.store.raw_log) > 50
    expected = snapshot(demo)
    demo.processor.replay()
    assert demo.db.count("raw_events") == raw_n       # replay rebuilds projections, never the source log

    rebuilt = Runtime(load_config(overrides=FAST), Persistence(url), live=True)
    rebuilt.rebuild()
    assert snapshot(rebuilt) == expected
    assert len(rebuilt.store.historical) == len(demo.store.historical) > 0


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setenv("LEADPILOT_MODE", "live")
    monkeypatch.setenv("LEADPILOT_PERSIST", "1")
    monkeypatch.setenv("LEADPILOT_DB_URL", f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as c:
        for _ in range(100):
            if c.get("/api/health").json()["status"] == "ready":
                break
            time.sleep(0.1)
        yield c


def test_live_api_refuses_simulator_controls(live_client):
    h = live_client.get("/api/health").json()
    assert h["mode"] == "live" and h["status"] == "ready"
    for path in ("/api/sim/start", "/api/sim/reset", "/api/sim/scenario/reviver"):
        assert live_client.post(path, json={}).status_code == 409
    r = live_client.post("/api/events", json=live_events(datetime.now(timezone.utc))).json()
    assert [x["status"] for x in r["results"]] == ["processed"] * 4
    assert live_client.get("/api/sim/status").json()["mode"] == "live"


def test_env_mode_is_validated(monkeypatch):
    from app.settings import get_settings
    monkeypatch.setenv("LEADPILOT_MODE", "staging")
    with pytest.raises(ValueError):
        get_settings()
    monkeypatch.setenv("LEADPILOT_MODE", "live")
    assert get_settings().live
    assert os.environ["LEADPILOT_MODE"] == "live"


def test_restart_skips_projection_rewrite_unless_config_changed(tmp_path):
    url = f"sqlite:///{tmp_path / 'lp.db'}"
    first = live_runtime(url)
    for e in live_events(first.clock.now()):
        first.emit(e)
    counts = {t: first.db.count(t) for t in ("events", "score_changes", "leads", "stage_transitions")}
    expected = snapshot(first)

    same = Runtime(load_config(), Persistence(url), live=True)
    assert same.rebuild()["rewrote_projections"] is False          # same rules: stored projections are current
    assert snapshot(same) == expected
    assert {t: same.db.count(t) for t in counts} == counts

    changed_cfg = load_config(overrides={"scoring": {"grades": {"A": 81}}})
    assert changed_cfg.fingerprint != same.cfg.fingerprint
    changed = Runtime(changed_cfg, Persistence(url), live=True)
    assert changed.rebuild()["rewrote_projections"] is True         # new rules: rewrite from the raw log
    assert changed.db.get_meta("projection_config") == changed_cfg.fingerprint
    assert changed.db.count("events") == counts["events"]


def test_mode_guard_protects_live_data_from_demo_resets(tmp_path):
    from app.runtime import ModeMismatch
    url = f"sqlite:///{tmp_path / 'lp.db'}"
    live = live_runtime(url)
    live.emit(live_events(live.clock.now())[0])
    demo = Runtime(load_config(overrides=FAST), Persistence(url))
    with pytest.raises(ModeMismatch, match="live-mode data"):
        demo.ensure_mode()
    demo.ensure_mode(allow_switch=True)                              # explicit override
    assert demo.db.count("raw_events") == 1                         # nothing was wiped by the check
    Runtime(load_config(), Persistence(f"sqlite:///{tmp_path / 'fresh.db'}"), live=True).ensure_mode()
