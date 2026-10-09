import pytest

from app.engine.priority import compute_priority, urgency_points


def test_urgency_scale(cfg):
    assert urgency_points(15, cfg) == 100
    assert urgency_points(60, cfg) == 100
    assert urgency_points(4320, cfg) == 0
    assert 0 < urgency_points(2000, cfg) < 100
    assert urgency_points(None, cfg) == 0


def test_priority_formula_and_drivers(cfg):
    r = compute_priority(score=80, ev=50000, p95_ev=100000, due_in_minutes=10, action_label="Demo requested 12 min ago",
                         stall_risk=0, stage="qualified", sla_minutes_left=None, cfg=cfg)
    assert r["priority"] == pytest.approx(0.4 * 80 + 0.25 * 50 + 0.2 * 100)
    assert r["drivers"][0]["label"] == "Score 80"
    assert any(d["label"] == "Demo requested 12 min ago" for d in r["drivers"])


def test_stall_rescue_only_for_qualified_plus(cfg):
    early = compute_priority(50, 0, 1, None, None, 80, "contacted", None, cfg)
    late = compute_priority(50, 0, 1, None, None, 80, "proposal", None, cfg)
    assert late["priority"] - early["priority"] == pytest.approx(0.15 * 80)


def test_sla_breach_bonus(cfg):
    base = compute_priority(50, 0, 1, None, None, 0, "new", None, cfg)
    soon = compute_priority(50, 0, 1, None, None, 0, "new", 10, cfg)
    assert soon["priority"] - base["priority"] == 15


def test_ev_normalized_and_capped(cfg):
    a = compute_priority(0, 300000, 100000, None, None, 0, "new", None, cfg)
    assert a["priority"] == pytest.approx(25)
