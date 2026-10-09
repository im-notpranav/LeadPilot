import pytest

from app.engine.metrics import engagement_metrics
from helpers import Builder, at


def test_response_times_and_streak(cfg):
    b = Builder()
    b.capture(cfg)                      # t=0 inbound
    b.ev("email_sent", 0.5)             # first response 30 min
    b.reply("thanks, interested", 2)    # prospect response 90 min
    b.ev("email_sent", 3)               # rep reply response 60 min
    b.ev("email_sent", 30)
    b.ev("call_logged", 50, outcome="no_answer")
    m = engagement_metrics(b.sorted(), at(51), cfg)
    assert m["first_response_minutes"] == pytest.approx(30)
    assert m["first_response_rep_id"] == "R-ANANYA"
    assert m["prospect_response_minutes"] == [pytest.approx(90)]
    assert m["reply_response_minutes"] == [pytest.approx(30), pytest.approx(60)]
    assert m["unanswered_outbound_streak"] == 3
    assert m["last_outbound_at"] == at(50)
    assert m["days_since_last_inbound"] == pytest.approx(49 / 24)


def test_engagement_velocity(cfg):
    b = Builder()
    b.capture(cfg)
    for d in (2, 3, 4, 5):
        b.page("blog", d * 24)
    b.page("pricing", 12 * 24)
    m = engagement_metrics(b.sorted(), at(12 * 24 + 1), cfg)
    assert m["engagement_prev_7d"] == 5 and m["engagement_7d"] == 1     # lead_created + 4 views in prev week
    assert m["engagement_velocity"] == pytest.approx(0.2)


def test_connected_call_resets_streak(cfg):
    b = Builder()
    b.capture(cfg)
    for h in (1, 2, 3):
        b.ev("email_sent", h)
    b.ev("call_logged", 4, outcome="connected")
    assert engagement_metrics(b.sorted(), at(5), cfg)["unanswered_outbound_streak"] == 0
