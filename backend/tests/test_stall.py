from app.engine.types import LeadContext
from helpers import Builder, at, evaluate_at


def proposal_lead(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.reply("Great, let's meet", 2)
    b.ev("meeting_held", 24)
    b.ev("proposal_sent", 26, amount=50000)
    return b


def test_s1_inactivity_beyond_stage_sla(cfg):
    b = proposal_lead(cfg)
    assert not evaluate_at(cfg, b.events, 24 + 6 * 24).stall["is_stalled"]
    st = evaluate_at(cfg, b.events, 24 + 8 * 24).stall
    assert st["is_stalled"] and "S1" in st["rules"] and 0.9 < st["days_over_sla"] < 1.1


def test_s4_ghosting_and_risk(cfg):
    b = proposal_lead(cfg)
    for d in (2, 4, 6):
        b.ev("email_sent", 26 + d * 24)
    st = evaluate_at(cfg, b.events, 24 + 8 * 24).stall
    assert {"S1", "S4"} <= set(st["rules"])
    assert st["risk"] == min(100, round(30 + 25 + 3 * st["days_over_sla"]))


def test_s2_overdue_task_and_expired_action(cfg):
    b = proposal_lead(cfg)
    b.ev("task_created", 27, task_id="t1", due_at="2026-10-06T12:00:00Z", task_type="send_case_study")
    assert "S2" in evaluate_at(cfg, b.events, 27 + 3 * 24).stall["rules"]
    b.ev("task_completed", 27 + 3 * 24, task_id="t1")
    assert "S2" not in evaluate_at(cfg, b.events, 27 + 3 * 24 + 1).stall["rules"]
    ctx = LeadContext(expired_actions=[at(27 + 2 * 24)])
    assert "S2" in evaluate_at(cfg, b.events, 27 + 3 * 24 + 1, ctx).stall["rules"]


def test_s3_velocity_drop(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.reply("happy to talk", 2)
    for i in range(5):
        b.page("product", 24 * (1 + i))
    b.page("blog", 24 * 9)
    st = evaluate_at(cfg, b.events, 24 * 13).stall
    assert "S3" in st["rules"]


def test_s5_no_next_step_after_meeting(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.ev("meeting_held", 2)
    b.page("product", 3)
    ev = evaluate_at(cfg, b.events, 3 + 4 * 24)
    assert ev.stage == "meeting" and "S5" not in ev.stall["rules"]
    st = evaluate_at(cfg, b.events, 3 + 6 * 24).stall
    assert "S5" in st["rules"]


def test_stall_clears_on_next_inbound(cfg):
    b = proposal_lead(cfg)
    for d in (2, 4, 6):
        b.ev("email_sent", 26 + d * 24)
    assert evaluate_at(cfg, b.events, 24 + 9 * 24).stall["is_stalled"]
    b.ev("proposal_viewed", 24 + 9 * 24 + 1)
    assert not evaluate_at(cfg, b.events, 24 + 9 * 24 + 1).stall["is_stalled"]


def test_no_stall_outside_active_pipeline(cfg):
    b = Builder()
    b.capture(cfg, capture_method="cold_import")
    assert not evaluate_at(cfg, b.events, 24 * 20).stall["is_stalled"]  # stage new
