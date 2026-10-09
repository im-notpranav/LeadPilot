from app.engine.types import LeadContext
from helpers import Builder, evaluate_at


def primary(cfg, b, hours, ctx=None):
    ev = evaluate_at(cfg, b.events, hours, ctx)
    return ev.nba[0]["rule_id"] if ev.nba else None, ev


def contacted(cfg, **kw):
    b = Builder()
    b.capture(cfg, capture_method="cold_import", **kw)
    b.ev("email_sent", 1)
    return b


def test_n1_fake_quarantine(cfg):
    b = Builder()
    b.capture(cfg, name="Xkcd Qwrtz", email="asdf@mailinator.com", company="Test", phone="9999999999",
              form_fill_seconds=1)
    rule, ev = primary(cfg, b, 1)
    assert rule == "N1" and len(ev.nba) == 1


def test_n2_demo_request(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("demo_request", 1)
    rule, ev = primary(cfg, b, 1.2)
    assert rule == "N2" and ev.nba[0]["due_minutes"] == 15
    assert "no meeting booked" in ev.nba[0]["reason"]
    b.ev("call_logged", 1.5, outcome="connected")
    assert primary(cfg, b, 1.6)[0] != "N2"


def test_n3_pricing_reply(cfg):
    b = contacted(cfg)
    b.reply("What is your pricing for 50 seats? We have budget this quarter.", 3)
    assert primary(cfg, b, 3.1)[0] == "N3"


def test_n4_pricing_views_no_contact(cfg):
    b = contacted(cfg)
    for h in (60, 70, 80):
        b.page("pricing", h)
    assert primary(cfg, b, 81)[0] == "N4"


def test_n5_trial_signup(cfg):
    b = contacted(cfg)
    b.ev("trial_signup", 5)
    assert primary(cfg, b, 5.5)[0] == "N5"


def test_n6_meeting_without_next_step(cfg):
    b = contacted(cfg)
    b.ev("meeting_held", 24, meeting_type="discovery")
    assert primary(cfg, b, 25)[0] == "N6"


def test_n7_stalled_proposal(cfg):
    b = contacted(cfg)
    b.reply("sounds good", 2)
    b.ev("meeting_held", 24)
    b.ev("proposal_sent", 26, amount=40000)
    assert primary(cfg, b, 26 + 9 * 24)[0] == "N7"


def test_n8_switch_channel(cfg):
    b = contacted(cfg)
    b.ev("email_sent", 48)
    b.ev("email_sent", 96)
    assert primary(cfg, b, 97)[0] == "N8"


def test_n9_no_show(cfg):
    b = contacted(cfg)
    b.ev("meeting_scheduled", 2, meeting_type="demo")
    b.ev("meeting_no_show", 30)
    assert primary(cfg, b, 31)[0] == "N9"


def test_n10_competitor_compare(cfg):
    b = contacted(cfg)
    b.page("competitor_compare", 5)
    assert primary(cfg, b, 6)[0] == "N10"


def test_n11_buying_committee(cfg):
    b = contacted(cfg)
    ctx = LeadContext(account_activity=[(b.events[0].ts, "L-2"), (b.events[0].ts, "L-3")])
    assert primary(cfg, b, 3, ctx)[0] == "N11"


def test_n12_first_touch_due_per_sla(cfg):
    b = Builder()
    b.capture(cfg)
    rule, ev = primary(cfg, b, 0.1)
    assert rule == "N12"
    assert ev.nba[0]["due_minutes"] == cfg.assignment.reassignment.first_touch_sla_minutes[ev.score.grade]


def test_n13_grade_d_inactive(cfg):
    b = contacted(cfg)
    b.ev("bant_qualified", 2)
    rule, ev = primary(cfg, b, 31 * 24)
    assert ev.stage == "qualified" and ev.score.grade == "D" and rule == "N13"


def test_n14_objection(cfg):
    b = contacted(cfg)
    b.reply("Honestly we already use HubSpot and this looks too expensive.", 3)
    assert primary(cfg, b, 3.5)[0] == "N14"


def test_n15_default_with_alternates_capped(cfg):
    b = contacted(cfg)
    b.reply("Thanks, will take a look.", 3)
    rule, ev = primary(cfg, b, 4)
    assert rule == "N15"
    assert len(ev.nba) <= 3


def test_no_actions_for_closed_deals(cfg):
    b = contacted(cfg)
    b.ev("deal_won", 5, amount=1000)
    assert evaluate_at(cfg, b.events, 6).nba == []
