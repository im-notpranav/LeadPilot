import pytest

from app.engine.prediction import close_probability, predict_acv
from app.engine.profile import build_profile
from app.engine.types import LeadContext
from helpers import Builder, evaluate_at


def test_acv_from_band_and_industry(cfg):
    b = Builder()
    b.capture(cfg)
    r = predict_acv(build_profile(b.events, cfg), b.events, cfg)
    assert r["acv"] == pytest.approx(45000 * 1.3)
    assert r["p10"] == pytest.approx(0.7 * r["acv"]) and r["p90"] == pytest.approx(1.3 * r["acv"])


def test_enterprise_plan_and_seats(cfg):
    b = Builder()
    b.capture(cfg)
    b.page("enterprise_plan", 1)
    assert predict_acv(build_profile(b.events, cfg), b.events, cfg)["acv"] == pytest.approx(45000 * 1.3 * 1.4)
    b.reply("We would need about 200 seats", 2)
    assert predict_acv(build_profile(b.events, cfg), b.events, cfg)["acv"] == pytest.approx(200 * 600)


def test_budget_caps_acv(cfg):
    b = Builder()
    b.capture(cfg, budget=30000)
    assert predict_acv(build_profile(b.events, cfg), b.events, cfg)["acv"] == pytest.approx(30000)
    b2 = Builder()
    b2.capture(cfg, budget=500000)
    assert predict_acv(build_profile(b2.events, cfg), b2.events, cfg)["acv"] == pytest.approx(1.5 * 45000 * 1.3)


def test_quoted_amount_wins(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("proposal_sent", 2, amount=72000)
    assert predict_acv(build_profile(b.events, cfg), b.events, cfg)["acv"] == 72000


def test_close_probability_by_stage_and_stall(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.reply("let's talk", 2)
    b.ev("meeting_held", 24)
    b.ev("proposal_sent", 26, amount=50000)
    fresh = evaluate_at(cfg, b.events, 27)
    stale = evaluate_at(cfg, b.events, 26 + 10 * 24)
    assert fresh.stage == "proposal"
    assert stale.stall["is_stalled"] and stale.close["p"] < fresh.close["p"]
    assert fresh.expected_value == pytest.approx(50000 * fresh.close["p"])
    assert {f["key"] for f in fresh.close["factors"]} == {"stage", "score", "intent", "rep", "stalled", "sla", "source"}


def test_close_probability_terminal(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("deal_won", 2, amount=1000)
    assert evaluate_at(cfg, b.events, 3).close["p"] == 1.0
    ev = evaluate_at(cfg, b.events, 3)
    lost = close_probability("lost", ev.score, ev.stall, LeadContext(), cfg)
    assert lost["p"] == 0.0


def test_better_rep_raises_probability(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("bant_qualified", 1)
    ev = evaluate_at(cfg, b.events, 2)
    lo = close_probability(ev.stage, ev.score, ev.stall, LeadContext(rep_segment_win_rate=0.15, team_win_rate=0.25), cfg)
    hi = close_probability(ev.stage, ev.score, ev.stall, LeadContext(rep_segment_win_rate=0.35, team_win_rate=0.25), cfg)
    assert hi["p"] > lo["p"]
