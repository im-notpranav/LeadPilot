import pytest

from app.engine.explain import diff
from app.engine.profile import build_profile
from app.engine.scoring import compute_score, grade_for
from app.engine.types import LeadContext
from helpers import Builder, at, evaluate_at


def score(cfg, b, hours, ctx=None):
    evs = [e for e in b.sorted() if e.ts <= at(hours)]
    return compute_score(build_profile(evs, cfg), evs, at(hours), ctx or LeadContext(), cfg)


def test_fit_for_icp_lead(cfg):
    b = Builder()
    b.capture(cfg)
    s = score(cfg, b, 0)
    assert s.fit == 38  # 14 size + 10 fintech + 6 director + 4 APAC + 4 business email
    assert s.factors["fit.company_size"].reason.startswith("300 employees")


def test_free_mail_unenriched_fit(cfg):
    b = Builder()
    b.capture(cfg, email="someone@gmail.com", company="", title="Student", country="IN")
    s = score(cfg, b, 0)
    assert s.factors["fit.business_email"].value == 0
    assert s.factors["fit.company_size"].value == 0
    assert "penalty.disqualifier" in s.factors


def test_half_life_decay(cfg):
    b = Builder()
    b.capture(cfg, capture_method="cold_import")
    b.ev("email_clicked", 0)
    assert score(cfg, b, 0).factors["engagement.email_clicked"].raw == pytest.approx(3.0)
    assert score(cfg, b, 5 * 24).factors["engagement.email_clicked"].raw == pytest.approx(1.5)


def test_repeat_decay_diminishing_returns(cfg):
    b = Builder()
    b.capture(cfg)
    b.page("pricing", 1)
    b.page("pricing", 1)
    b.page("pricing", 1)
    raw = score(cfg, b, 1).factors["intent.pricing_view"].raw
    assert raw == pytest.approx(6 * (1 + 0.7 + 0.49))


def test_saturation_never_exceeds_caps(cfg):
    b = Builder()
    b.capture(cfg)
    for i in range(60):
        b.page("pricing", i * 0.1)
        b.ev("demo_request", i * 0.1)
        b.ev("webinar_attended", i * 0.1)
        b.ev("email_clicked", i * 0.1)
    s = score(cfg, b, 6)
    assert s.engagement < 35 and s.intent < 25 and s.score <= 100


def test_intent_burst_bonus_window(cfg):
    b = Builder()
    b.capture(cfg)
    b.page("pricing", 1)
    b.page("pricing", 20)
    b.page("competitor_compare", 40)
    assert "intent.intent_burst_bonus" in score(cfg, b, 41).factors
    assert "intent.intent_burst_bonus" not in score(cfg, b, 1 + 72 + 1).factors


def test_buying_committee_from_context(cfg):
    b = Builder()
    b.capture(cfg)
    ctx = LeadContext(account_activity=[(at(-24), "L-2"), (at(-30), "L-3")])
    s = score(cfg, b, 0, ctx)
    assert "intent.buying_committee" in s.factors
    old = LeadContext(account_activity=[(at(-24 * 20), "L-2"), (at(-30), "L-3")])
    assert "intent.buying_committee" not in score(cfg, b, 0, old).factors


def test_penalties(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.ev("email_sent", 30)
    b.ev("email_sent", 60)
    s = score(cfg, b, 61)
    assert s.factors["penalty.unanswered_streak"].value == -5
    s20 = score(cfg, b, 20 * 24)
    assert s20.factors["penalty.staleness"].value == -6     # 20 days, 14 grace
    assert score(cfg, b, 60 * 24).factors["penalty.staleness"].value == -10  # capped
    b.ev("email_bounced", 62)
    b.ev("unsubscribed", 63)
    b.reply("Not interested, please remove me", 64)
    s = score(cfg, b, 64)
    assert s.factors["penalty.email_bounced"].value == -10
    assert s.factors["penalty.unsubscribed"].value == -15
    assert s.factors["penalty.negative_reply"].value == -20


def test_no_show_penalty_decays(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("meeting_no_show", 1)
    assert score(cfg, b, 1).factors["penalty.meeting_no_show"].value == pytest.approx(-6)
    assert score(cfg, b, 1 + 14 * 24).factors["penalty.meeting_no_show"].value == pytest.approx(-3)


def test_quality_risk_penalty(cfg):
    b = Builder()
    b.capture(cfg, name="Maria Lopez", email="info@yopmail.com", company="", country="US", ip="23.1.1.1")
    s = score(cfg, b, 0)
    assert s.factors["penalty.quality_risk"].value == pytest.approx(-(45 - 40) / 3)


def test_clamp_factor_keeps_score_in_bounds(cfg):
    b = Builder()
    b.capture(cfg, email="kid@gmail.com", company="", title="Student", country="BR")
    b.ev("email_bounced", 1)
    b.ev("unsubscribed", 1)
    b.reply("not interested, remove me", 2)
    s = score(cfg, b, 2)
    assert s.score == 0
    assert "clamp" in s.factors
    assert sum(f.value for f in s.factors.values()) == pytest.approx(0.0)


def test_score_changes_on_every_prospect_event(cfg):
    b = Builder()
    b.capture(cfg)
    prev = score(cfg, b, 0).score
    for i, (kind, cat) in enumerate([("page_view", "pricing"), ("content_download", None), ("page_view", "case_study"),
                                     ("demo_request", None), ("webinar_attended", None)]):
        h = 1 + i
        if kind == "page_view":
            b.page(cat, h)
        else:
            b.ev(kind, h)
        now = score(cfg, b, h).score
        assert now != prev
        prev = now


def test_i8_inactivity_lowers_score_and_cites_decay(cfg):
    """I8: with no new events, advancing 14 days lowers an engaged lead's score; the change cites decay."""
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.reply("Sounds good, let's talk next week", 3)
    b.page("pricing", 4)
    before = evaluate_at(cfg, b.events, 5)
    after = evaluate_at(cfg, b.events, 5 + 14 * 24)
    assert before.stage == "engaged"
    assert after.score.score < before.score.score
    contribs = diff(before.score.factors, after.score.factors, cfg)
    reasons = " ".join(c["reason"] for c in contribs).lower()
    assert "aged" in reasons or "expired" in reasons or "no prospect activity" in reasons
    assert all(c["delta"] <= 1e-9 for c in contribs)


def test_grades(cfg):
    assert grade_for(80, cfg) == "A" and grade_for(79.9, cfg) == "B"
    assert grade_for(60, cfg) == "B" and grade_for(40, cfg) == "C" and grade_for(39.9, cfg) == "D"


def test_intent_level_hot_on_recent_demo(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("demo_request", 1)
    assert score(cfg, b, 2).intent_level == "hot"
    assert score(cfg, b, 60).intent_level != "hot"
