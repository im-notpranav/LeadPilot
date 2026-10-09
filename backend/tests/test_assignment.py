from datetime import timedelta

import pytest

from app.engine.assignment import check_reassignment, choose_rep, lead_facts, smoothed_win_rate
from app.engine.profile import build_profile
from helpers import Builder, at


def facts(cfg, grade="C", intent="low", **capture):
    b = Builder()
    b.capture(cfg, **capture)
    return lead_facts(build_profile(b.events, cfg), grade, intent, cfg)


def test_priya_goes_to_fintech_apac_rep(cfg):
    r = choose_rep(facts(cfg), cfg.data.reps, {}, 0.25, cfg)
    assert r["rep_id"] == "R-ANANYA"
    assert "fintech specialist" in r["reason"] and "capacity free" in r["reason"]
    assert len(r["candidates"]) == len(cfg.data.reps)


def test_hot_large_account_prefers_enterprise_reps(cfg):
    f = facts(cfg, grade="A", intent="hot", name="Dana Wells", email="dana@helixhealth.com", company="Helix Health",
              title="VP Operations", country="US")
    r = choose_rep(f, cfg.data.reps, {}, 0.25, cfg)
    rep = next(x for x in cfg.data.reps if x["rep_id"] == r["rep_id"])
    assert "enterprise" in rep["tags"] and r["rep_id"] == "R-MARCUS"


def test_capacity_filter(cfg):
    stats = {"R-ANANYA": {"load": 40}}
    r = choose_rep(facts(cfg), cfg.data.reps, stats, 0.25, cfg)
    assert r["rep_id"] != "R-ANANYA"
    assert r["rep_id"] in ("R-KENJI",)  # the only other rep covering APAC (global)


def test_relax_territory_when_nobody_covers_region(cfg):
    reps = [r for r in cfg.data.reps if r["rep_id"] in ("R-SOPHIE", "R-DANIEL")]
    r = choose_rep(facts(cfg), reps, {}, 0.25, cfg)
    assert r["rep_id"] in ("R-SOPHIE", "R-DANIEL") and r["relaxed"] == ["territory"]
    assert "relaxed constraint: territory" in r["reason"]


def test_fairness_tie_break(cfg):
    base = dict(cfg.data.reps[0])
    a = dict(base, rep_id="R-A", name="Alpha Rep")
    b = dict(base, rep_id="R-B", name="Beta Rep")
    stats = {"R-A": {"last_assigned_at": at(-1)}, "R-B": {"last_assigned_at": at(-10)}}
    assert choose_rep(facts(cfg), [a, b], stats, 0.25, cfg)["rep_id"] == "R-B"


def test_exclude_current_owner(cfg):
    r = choose_rep(facts(cfg), cfg.data.reps, {}, 0.25, cfg, exclude=("R-ANANYA",))
    assert r["rep_id"] != "R-ANANYA"


def test_smoothed_win_rate(cfg):
    assert smoothed_win_rate(0, 0, 0.25, cfg) == pytest.approx(0.25)
    assert smoothed_win_rate(10, 20, 0.25, cfg) == pytest.approx(12 / 28)


def test_r1_first_touch_sla(cfg):
    lead = {"owner": "R-VICTOR", "assigned_at": at(0), "stage": "qualified", "grade": "A", "last_outbound_at": None}
    assert check_reassignment(lead, at(0) + timedelta(minutes=59), cfg) is None
    r = check_reassignment(lead, at(0) + timedelta(minutes=61), cfg)
    assert r["rule"] == "R1"
    touched = dict(lead, last_outbound_at=at(0.5))
    assert check_reassignment(touched, at(0) + timedelta(minutes=61), cfg) is None


def test_r2_open_deal_neglect(cfg):
    lead = {"owner": "R-EMILY", "assigned_at": at(0), "stage": "proposal", "grade": "B",
            "last_outbound_at": at(1), "last_rep_activity_at": at(1)}
    assert check_reassignment(lead, at(1 + 6 * 24), cfg) is None
    assert check_reassignment(lead, at(1 + 7 * 24 + 1), cfg)["rule"] == "R2"


def test_r2_clock_starts_at_stage_entry(cfg):
    """A deal that has just been qualified is not 'neglected' because the last rep touch was long ago."""
    lead = {"owner": "R-ANANYA", "assigned_at": at(-24 * 40), "stage": "qualified", "grade": "B",
            "last_outbound_at": at(-24 * 34), "last_rep_activity_at": at(-24 * 34), "stage_entered_at": at(0)}
    assert check_reassignment(lead, at(24 * 6), cfg) is None
    assert check_reassignment(lead, at(24 * 7 + 1), cfg)["rule"] == "R2"


def test_no_reassignment_from_manager_queue(cfg):
    lead = {"owner": "manager_queue", "assigned_at": at(0), "stage": "new", "grade": "A", "last_outbound_at": None}
    assert check_reassignment(lead, at(100), cfg) is None
