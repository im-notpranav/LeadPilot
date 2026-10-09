"""Each scripted demo scenario produces its expected outcome (M7)."""
from datetime import timedelta

import pytest

from app.runtime import Runtime


@pytest.fixture
def rt(cfg):
    r = Runtime(cfg)
    r.reset(warmup=False, background=False, rep_actions=False)
    return r


def advance(rt, hours):
    rt.run_until(rt.clock.now() + timedelta(hours=hours))


def test_reviver(rt):
    info = rt.launch_scenario("reviver")
    lead = rt.store.leads[info["lead_id"]]
    assert lead.ev.score.grade == "D" and lead.ev.score.score < 35
    assert lead.stage == "nurture"
    start_close = lead.ev.close["p"]
    advance(rt, 15)
    ev = lead.ev
    assert 68 <= ev.score.score <= 85
    assert ev.score.intent_level == "hot"
    assert ev.stage == "qualified"
    assert lead.owner == "R-ANANYA"
    act = lead.open_action()
    assert act["rule_id"] == "N2" and act["action"] == "Call now and book a demo"
    assert (act["due_at"] - act["ts"]) == timedelta(minutes=15)
    rules = [t["rule_id"] for t in lead.transitions]
    assert "P10" in rules and "P3" in rules
    demo_row = next(r for r in lead.score_history if r["event_type"] == "demo_request")
    assert any(c["key"] == "intent.demo_request" and c["delta"] > 0 for c in demo_row["contributions"])
    assert "requested a demo" in demo_row["summary"]
    assert ev.close["p"] > start_close


def test_ghoster(rt):
    info = rt.launch_scenario("ghoster")
    lead = rt.store.leads[info["lead_id"]]
    assert lead.stage == "proposal" and not lead.is_stalled
    start_close = lead.ev.close["p"]
    start_score = lead.ev.score.score
    advance(rt, 24 * 8)
    ev = lead.ev
    assert ev.stall["is_stalled"]
    assert {"S1", "S4"} <= set(ev.stall["rules"])
    assert lead.open_action()["rule_id"] == "N7"
    assert ev.close["p"] < start_close
    assert ev.score.score < start_score
    ticks = [r for r in lead.score_history if r["event_type"] == "time_tick" and r["delta"] < 0]
    assert ticks and all(r["contributions"] for r in ticks)
    assert any(f["rule_ids"] for f in lead.stall_flags)


def test_duplicate(rt):
    info = rt.launch_scenario("duplicate")
    advance(rt, 1)
    survivor = rt.store.leads[info["lead_id"]]
    merge = rt.store.merges[-1]
    assert merge["survivor_id"] == survivor.lead_id and merge["confidence"] == 1.0 and merge["mode"] == "auto"
    dup = rt.store.leads[merge["merged_id"]]
    assert dup.status == "merged" and dup.merged_into == survivor.lead_id
    row = next(r for r in survivor.score_history if r["contributions"] and r["contributions"][0]["key"] == "merge")
    assert row["contributions"][0]["reason"].startswith(f"Merged duplicate {dup.lead_id} (same email via google_ads)")
    assert set(survivor.profile.sources) == {"webinar", "google_ads"}
    assert survivor.profile.phone_e164 == "+919820123456"


def test_bot_burst(rt):
    rt.launch_scenario("bot_burst")
    advance(rt, 1.5)
    bots = [l for l in rt.store.leads.values() if l.source == "list_vendor_x"]
    assert len(bots) == 20
    assert all(l.status == "quarantined" and l.stage == "disqualified" and l.owner is None for l in bots)
    assert all(l.open_action() is None or l.open_action()["rule_id"] == "N1" for l in bots)
    sq = rt.store.source_stats["list_vendor_x"]
    assert sq["flagged"] and any("fake" in r for r in sq["flag_reasons"])


def test_neglected_hot_lead(rt):
    info = rt.launch_scenario("neglected")
    lead = rt.store.leads[info["lead_id"]]
    assert lead.ev.score.grade == "A"
    assert lead.owner == "R-VICTOR"
    advance(rt, 0.9)
    assert lead.owner == "R-VICTOR"
    advance(rt, 0.6)
    assert lead.owner not in ("R-VICTOR", None)
    last = lead.assignments[-1]
    assert last["rule_id"] == "R1" and last["previous_rep_id"] == "R-VICTOR" and last["type"] == "reassign"
    assert last["reason"].startswith("R1: No first touch")
    assert rt.store.rep_stats["R-VICTOR"]["neglect_count"] >= 1
