import random

from app.engine.evaluate import evaluate
from app.engine.pipeline import FoldState, fold_step, run_fold
from app.engine.types import LeadContext, Profile
from helpers import Builder, at, evaluate_at, fold


def stages(trans):
    return [(t.from_stage, t.to_stage, t.rule_id) for t in trans]


def test_p1_contacted(cfg):
    b = Builder()
    b.capture(cfg, capture_method="cold_import")
    b.ev("email_sent", 1)
    st, tr = fold(cfg, b.events)
    assert st.stage == "contacted" and stages(tr) == [("new", "contacted", "P1")]


def test_p2_engaged_on_non_negative_reply_only(cfg):
    b = Builder()
    b.capture(cfg, capture_method="cold_import", email="x@gmail.com", company="")
    b.ev("email_sent", 1)
    b.reply("Not interested, remove me", 2)
    assert fold(cfg, b.events)[0].stage == "contacted"
    b.reply("Actually, happy to chat next week", 3)
    assert fold(cfg, b.events)[0].stage == "engaged"


def test_p3_demo_request_skips_stages_with_intermediate_transitions(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("demo_request", 1)
    st, tr = fold(cfg, b.events)
    assert st.stage == "qualified"
    assert stages(tr) == [("new", "contacted", "P3"), ("contacted", "engaged", "P3"), ("engaged", "qualified", "P3")]
    assert all(t.evidence for t in tr)


def test_p3_requires_fit(cfg):
    b = Builder()
    b.capture(cfg, email="kid@gmail.com", company="", title="Student", country="IN")
    b.ev("demo_request", 1)
    assert fold(cfg, b.events)[0].stage == "new"


def test_p3_bant_qualified(cfg):
    b = Builder()
    b.capture(cfg, capture_method="cold_import")
    b.ev("email_sent", 1)
    b.ev("bant_qualified", 2)
    assert fold(cfg, b.events)[0].stage == "qualified"


def test_p4_p5_p6_p7(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("email_sent", 1)
    b.ev("meeting_held", 24, meeting_type="discovery")
    assert fold(cfg, b.events)[0].stage == "meeting"
    b.ev("proposal_sent", 48, amount=60000)
    assert fold(cfg, b.events)[0].stage == "proposal"
    b.reply("Looks good. Can we discuss a discount and the contract terms?", 60)
    assert fold(cfg, b.events)[0].stage == "negotiation"
    b.ev("deal_won", 100, amount=55000)
    st, tr = fold(cfg, b.events)
    assert st.stage == "won" and tr[-1].rule_id == "P7"
    b.ev("email_sent", 120)
    assert fold(cfg, b.events)[0].stage == "won"


def test_p6_contract_sent(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("proposal_sent", 2)
    b.ev("contract_sent", 3)
    assert fold(cfg, b.events)[0].stage == "negotiation"


def test_p8_deal_lost_and_negative_silence(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("proposal_sent", 2)
    b.ev("deal_lost", 3, lost_reason="price")
    assert fold(cfg, b.events)[0].stage == "lost"

    b2 = Builder()
    b2.capture(cfg)
    b2.ev("email_sent", 1)
    b2.ev("meeting_held", 2)
    b2.reply("Not interested anymore, remove me", 3)
    assert evaluate_at(cfg, b2.events, 3 + 29 * 24).stage == "meeting"
    ev = evaluate_at(cfg, b2.events, 3 + 31 * 24)
    assert ev.stage == "lost" and ev.transitions[-1].rule_id == "P8"


def test_p9_nurture_and_p10_revive(cfg):
    b = Builder()
    b.capture(cfg, email="sam@gmail.com", company="", title="Analyst", country="US")
    b.ev("email_sent", 1)
    ev = evaluate_at(cfg, b.events, 31 * 24)
    assert ev.stage == "nurture" and ev.transitions[-1].rule_id == "P9"
    b2 = Builder()
    b2.capture(cfg)                                  # high fit, gone quiet
    b2.ev("email_sent", 1)
    assert evaluate_at(cfg, b2.events, 35 * 24).stage == "nurture"
    b2.page("pricing", 35 * 24 + 1)
    st, tr = fold(cfg, b2.events)
    assert st.stage == "engaged"
    assert ("contacted", "nurture", "P9") in stages(tr) and ("nurture", "engaged", "P10") in stages(tr)


def test_p11_disqualify_fake_and_restore(cfg):
    b = Builder()
    b.capture(cfg, name="Xkcd Qwrtz", email="asdf@mailinator.com", company="Test", phone="9999999999",
              form_fill_seconds=1)
    st, tr = fold(cfg, b.events)
    assert st.stage == "disqualified" and tr[-1].rule_id == "P11"
    b.ev("quality_cleared", 5)
    st, tr = fold(cfg, b.events)
    assert st.stage == "new" and tr[-1].rule_id == "Q1" and tr[-1].mode == "manual"

    b2 = Builder()
    b2.capture(cfg)
    b2.ev("lead_disqualified", 2, reason="Job seeker")
    st, tr = fold(cfg, b2.events)
    assert st.stage == "disqualified" and tr[-1].mode == "manual"


def test_manual_override_is_logged_and_can_move_backward(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("proposal_sent", 2)
    b.ev("stage_override", 3, to_stage="engaged", reason="Proposal withdrawn")
    st, tr = fold(cfg, b.events)
    assert st.stage == "engaged" and tr[-1].rule_id == "M1" and tr[-1].mode == "manual"


def test_auto_moves_are_forward_only(cfg):
    b = Builder()
    b.capture(cfg)
    b.ev("proposal_sent", 2)
    b.ev("email_sent", 3)
    b.reply("thanks, reviewing internally", 4)
    assert fold(cfg, b.events)[0].stage == "proposal"


def _mixed_history(cfg, seed):
    rng = random.Random(seed)
    b = Builder()
    b.capture(cfg)
    h = 0
    for _ in range(40):
        h += rng.choice([1, 5, 24, 24 * 5, 24 * 12])
        k = rng.choice(["email_sent", "reply", "page", "meeting_held", "proposal_sent", "demo_request",
                        "call", "neg", "stage_override"])
        if k == "reply":
            b.reply("sounds good, what is the pricing?", h)
        elif k == "neg":
            b.reply("not interested", h)
        elif k == "page":
            b.page(rng.choice(["pricing", "blog"]), h)
        elif k == "call":
            b.ev("call_logged", h, outcome=rng.choice(["connected", "voicemail"]))
        elif k == "stage_override":
            if rng.random() < 0.2:
                b.ev("stage_override", h, to_stage=rng.choice(["engaged", "qualified"]))
        else:
            b.ev(k, h)
    return b


def test_i7_every_transition_has_rule_and_evidence(cfg):
    for seed in range(8):
        b = _mixed_history(cfg, seed)
        evs = b.sorted()
        st, tr = run_fold(evs, LeadContext(), cfg)
        final = evaluate(st, evs, evs[-1].ts.replace() + (evs[-1].ts - evs[0].ts), LeadContext(), cfg)
        for t in tr + final.transitions:
            assert t.rule_id
            assert t.mode == "manual" or len([e for e in t.evidence if e]) >= 1


def test_i5_order_independence_engine_level(cfg):
    """Shuffled arrival + incremental fold with refold-on-late-event == fold over sorted events."""
    for seed in range(6):
        b = _mixed_history(cfg, seed)
        sorted_evs = b.sorted()
        expected, _ = run_fold(sorted_evs, LeadContext(), cfg)
        arrival = list(b.events)
        random.Random(seed).shuffle(arrival)
        state, seen = FoldState(profile=Profile(lead_id="L-1001")), []
        for e in arrival:
            seen.append(e)
            seen.sort(key=lambda x: x.sort_key)
            if state.last_key is None or e.sort_key > state.last_key:
                state, _ = fold_step(state, e, seen, LeadContext(), cfg)
            else:
                state, _ = run_fold(seen, LeadContext(), cfg, lead_id="L-1001")
        now = at(24 * 400)
        a = evaluate(state, seen, now, LeadContext(), cfg)
        b_ = evaluate(expected, sorted_evs, now, LeadContext(), cfg)
        assert (a.stage, round(a.score.score, 6), a.stall["is_stalled"]) == (b_.stage, round(b_.score.score, 6),
                                                                              b_.stall["is_stalled"])
