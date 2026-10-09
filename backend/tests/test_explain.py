import random

import pytest

from app.engine.explain import diff, merge_contribution, summary
from app.engine.profile import build_profile
from app.engine.scoring import compute_score
from app.engine.types import LeadContext
from helpers import Builder, at

KINDS = ["page_view:pricing", "page_view:blog", "page_view:case_study", "page_view:competitor_compare",
         "content_download", "email_opened", "email_clicked", "demo_request", "webinar_attended", "email_sent",
         "reply:positive", "reply:negative", "meeting_no_show", "call_logged:connected", "email_bounced",
         "proposal_viewed", "trial_signup"]


def _add(b, kind, h):
    if kind.startswith("page_view:"):
        b.page(kind.split(":")[1], h)
    elif kind == "reply:positive":
        b.reply("Can you share pricing for 40 seats and a timeline?", h)
    elif kind == "reply:negative":
        b.reply("Not interested, remove me", h)
    elif kind == "call_logged:connected":
        b.ev("call_logged", h, outcome="connected")
    else:
        b.ev(kind, h)


def _score(cfg, b, h, ctx=None):
    evs = [e for e in b.sorted() if e.ts <= at(h)]
    return compute_score(build_profile(evs, cfg), evs, at(h), ctx or LeadContext(), cfg)


@pytest.mark.parametrize("seed", range(12))
def test_i2_contributions_sum_to_delta(cfg, seed):
    """I2: for every score change, sum(contribution.delta) == new - old (+-0.01), clamp included."""
    rng = random.Random(seed)
    b = Builder()
    b.capture(cfg, email=rng.choice(["p@finnova.sg", "x@gmail.com"]), title=rng.choice(["CEO", "Intern", "Analyst"]))
    prev = _score(cfg, b, 0)
    h = 0.0
    for _ in range(80):
        h += rng.choice([0.1, 1, 6, 24, 72, 24 * 9])
        if rng.random() < 0.7:
            _add(b, rng.choice(KINDS), h)
        ctx = LeadContext(account_activity=[(at(h - 1), "L-9"), (at(h - 2), "L-8")]) if rng.random() < 0.2 else None
        new = _score(cfg, b, h, ctx)
        contribs = diff(prev.factors, new.factors, cfg)
        assert sum(c["delta"] for c in contribs) == pytest.approx(new.score - prev.score, abs=0.01)
        prev = new


def test_new_signal_gets_credit_old_signals_only_decay(cfg):
    b = Builder()
    b.capture(cfg)
    b.page("pricing", 1)
    b.page("pricing", 20)
    before = _score(cfg, b, 22)
    b.ev("demo_request", 22)
    after = _score(cfg, b, 22)
    contribs = {c["key"]: c for c in diff(before.factors, after.factors, cfg)}
    assert contribs["intent.demo_request"]["delta"] > 5
    assert "intent.pricing_view" not in contribs  # unchanged raw -> no charge


def test_first_snapshot_explains_from_zero(cfg):
    b = Builder()
    b.capture(cfg)
    s = _score(cfg, b, 0)
    contribs = diff(None, s.factors, cfg)
    assert sum(c["delta"] for c in contribs) == pytest.approx(s.score, abs=0.01)
    assert any(c["key"] == "fit.industry_icp" for c in contribs)


def test_rendered_text_and_summary(cfg):
    b = Builder()
    b.capture(cfg)
    before = _score(cfg, b, 1)
    b.ev("demo_request", 1)
    after = _score(cfg, b, 1)
    contribs = diff(before.factors, after.factors, cfg)
    assert any(c["text"].startswith("+") and "Intent" in c["text"] for c in contribs)
    text = summary(before.score, after.score, contribs, "demo_request", after.factors)
    assert "requested a demo" in text and text.startswith("Score ")


def test_summary_when_unchanged(cfg):
    assert summary(50, 50, [], "email_sent", {}).startswith("Score unchanged at 50: email sent")


def test_merge_contribution_preserves_sum(cfg):
    contribs = [{"key": "engagement.webinar_attended", "category": "engagement", "delta": 6.0},
                {"key": "intent.pricing_view", "category": "intent", "delta": 3.0},
                {"key": "minor", "category": "minor", "delta": -0.2}]
    merged = merge_contribution(contribs, "L-1219", "same email via webinar")
    assert len(merged) == 1 and merged[0]["key"] == "merge"
    assert merged[0]["delta"] == pytest.approx(8.8)
    assert "Merged duplicate L-1219 (same email via webinar)" in merged[0]["reason"]
