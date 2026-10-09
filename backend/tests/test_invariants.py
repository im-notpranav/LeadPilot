"""Mandatory invariants I1-I6 at the processor / runtime level (I2, I5, I7, I8 also have engine-level tests)."""
import random
from datetime import timedelta

import pytest

from app.config import load_config
from app.engine.types import iso
from app.persistence import Persistence
from app.processor import GLOBAL_TYPES
from app.runtime import Runtime

FAST = {"simulator": {"warmup_days": 4}}


def snapshot(rt) -> dict:
    out = {}
    for lid, l in sorted(rt.store.leads.items()):
        if l.ev is None:
            out[lid] = (l.status, l.merged_into)
            continue
        out[lid] = (l.status, l.merged_into, l.ev.stage, round(l.ev.score.score, 6), l.ev.score.grade, l.owner,
                    l.ev.stall["is_stalled"], round(l.ev.close["p"], 6), round(l.ev.acv["acv"], 2),
                    l.ev.score.intent_level, len(l.events))
    return out


def assignments(rt) -> list:
    return [(a["lead_id"], a["rep_id"], a["type"], a["rule_id"]) for l in rt.store.leads.values()
            for a in l.assignments]


@pytest.fixture(scope="module")
def live(cfg):
    """A live run: warm-up + a scenario + one simulated day, persisted to an in-memory SQLite database."""
    c = load_config(overrides=FAST)
    rt = Runtime(c, Persistence("sqlite:///:memory:"))
    rt.reset(seed=7)
    rt.launch_scenario("duplicate")
    rt.launch_scenario("reviver")
    rt.run_until(rt.clock.now() + timedelta(hours=26))
    return rt


def test_i1_every_lead_event_has_snapshot_and_score_row(live):
    rows_by_event = {}
    for l in live.store.leads.values():
        for r in l.score_history:
            rows_by_event.setdefault(r["event_id"], r)
    lead_events = [e for e in live.store.log if e.lead_id is not None and e.type not in GLOBAL_TYPES]
    assert len(lead_events) > 300
    missing = [e.event_id for e in lead_events if e.event_id not in rows_by_event]
    assert missing == []
    db = live.db
    assert db.count("factor_snapshots") == db.count("score_changes")
    assert db.count("score_changes") >= len(lead_events)


def test_i2_contributions_sum_to_delta_for_every_stored_change(live):
    n = 0
    for l in live.store.leads.values():
        prev = 0.0
        for r in l.score_history:
            assert r["old_score"] == pytest.approx(prev, abs=1e-9)
            assert sum(c["delta"] for c in r["contributions"]) == pytest.approx(r["new_score"] - r["old_score"], abs=0.01)
            prev = r["new_score"]
            n += 1
    assert n > 300


def test_i7_every_logged_transition_has_rule_and_evidence(live):
    for l in live.store.leads.values():
        for t in l.transitions:
            assert t["rule_id"]
            assert t["mode"] == "manual" or len(t["evidence_event_ids"]) >= 1


def test_i3_determinism_same_seed_same_outcome():
    c = load_config(overrides=FAST)
    a, b = Runtime(c), Runtime(c)
    for rt in (a, b):
        rt.reset(seed=11)
        rt.launch_scenario("neglected")
        rt.run_until(rt.clock.now() + timedelta(hours=12))
    assert snapshot(a) == snapshot(b)
    assert assignments(a) == assignments(b)
    c2 = Runtime(c)
    c2.reset(seed=12)
    assert snapshot(c2) != snapshot(a)


def test_i4_replay_rebuilds_identical_projections(live):
    before = snapshot(live)
    before_assign = assignments(live)
    before_rows = sum(len(l.score_history) for l in live.store.leads.values())
    live.processor.replay()
    assert snapshot(live) == before
    assert assignments(live) == before_assign
    assert sum(len(l.score_history) for l in live.store.leads.values()) == before_rows


def test_i6_idempotent_reingest(live):
    before = snapshot(live)
    n_log = len(live.store.log)
    sample = [r for r in live.store.raw_log if r["type"] != "time_tick"][-50:]
    for r in sample:
        assert live.processor.handle(dict(r))["status"] == "duplicate"
    assert snapshot(live) == before
    assert len(live.store.log) == n_log


def _lead_stream(cfg):
    T = "2026-10-05T09:00:00Z"
    base = {"lead_created": {"name": "Ana Silva", "email": "ana@acme.io", "company": "Acme", "title": "VP Sales",
                             "country": "IN", "capture_method": "form_submit", "ip": "103.1.1.1"}}
    evs = [{"event_id": "x000", "type": "lead_created", "ts": T, "source": "website", "payload": base["lead_created"]}]
    kinds = [("page_view", {"page_category": "pricing"}), ("email_sent", {}), ("email_opened", {}),
             ("email_replied", {"body": "What is the pricing for 30 seats?"}), ("meeting_scheduled", {}),
             ("meeting_held", {"meeting_type": "discovery"}), ("page_view", {"page_category": "case_study"}),
             ("proposal_sent", {"amount": 52000}), ("proposal_viewed", {}), ("email_sent", {}), ("email_sent", {}),
             ("content_download", {}), ("demo_request", {}), ("email_replied", {"body": "thanks, reviewing"})]
    rng = random.Random(3)
    t = 0.0
    for i, (k, pl) in enumerate(kinds, 1):
        t += rng.uniform(1, 40)
        actor = "rep" if k in ("email_sent", "meeting_scheduled", "meeting_held", "proposal_sent") else "prospect"
        ts = iso(load_config.__globals__["__builtins__"] and __import__("app.engine.types", fromlist=["parse_ts"])
                 .parse_ts(T) + timedelta(hours=t))
        evs.append({"event_id": f"x{i:03d}", "type": k, "ts": ts, "actor": actor,
                    "rep_id": "R-ROHAN" if actor == "rep" else None, "payload": pl})
    return evs, iso(__import__("app.engine.types", fromlist=["parse_ts"]).parse_ts(T) + timedelta(days=30))


def _run_stream(cfg, events, final_ts):
    rt = Runtime(cfg)
    rt.reset(warmup=False, background=False, rep_actions=False)
    lead_id = None
    for e in events:
        e = dict(e)
        e["ingested_at"] = final_ts
        if lead_id:
            e["lead_ref"] = {"lead_id": lead_id}
        r = rt.processor.handle(e)
        lead_id = lead_id or r["lead_id"]
    rt.processor.handle({"event_id": "refresh", "type": "lead_refresh", "ts": final_ts, "ingested_at": final_ts,
                         "actor": "system", "lead_ref": {"lead_id": lead_id}})
    l = rt.store.leads[lead_id]
    return (l.ev.stage, round(l.ev.score.score, 6), l.ev.score.intent_level, l.ev.stall["is_stalled"],
            round(l.ev.acv["acv"], 2), round(l.ev.close["p"], 6))


def test_i5_order_independence_processor_level(cfg):
    events, final_ts = _lead_stream(cfg)
    expected = _run_stream(cfg, events, final_ts)
    for seed in range(4):
        rest = events[1:]
        random.Random(seed).shuffle(rest)
        assert _run_stream(cfg, [events[0]] + rest, final_ts) == expected
