"""Next-best-action (pure). Ordered rules; first match is primary, the next two are alternates.

Triggers use "unaddressed" semantics: a signal only triggers an action if it happened after the last rep
outbound, so an action naturally completes when the rep acts and the next rule takes over.
"""
from __future__ import annotations

from .intent import has_pricing_terms, reply_class
from .types import Event, Profile, ScoreResult, age_days, age_hours


def _fmt(hours: float) -> str:
    if hours < 1:
        return f"{max(1, int(hours * 60))} min"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


def build_facts(stage: str, p: Profile, score: ScoreResult, metrics: dict, stall: dict, events: list[Event], now,
                cfg) -> dict:
    w = cfg.nba.recent_windows
    last_out = metrics.get("last_outbound_at")
    f = {"stage": stage, "fake": p.fake_status == "fake", "grade": score.grade, "streak": metrics.get(
        "unanswered_outbound_streak", 0), "is_stalled": stall.get("is_stalled"), "contacted": last_out is not None,
         "days_since_inbound": metrics.get("days_since_last_inbound") or 0,
         "buying_committee": "intent.buying_committee" in score.factors}
    last_demo = last_meeting_sched = last_connected = last_meeting_held = last_no_show = None
    last_reply = last_trial = last_competitor = None
    pricing_72 = 0
    group_demo_sent = None
    last_out_channel = None
    proposal_after_meeting = False
    for e in events:
        if e.ts > now:
            break
        t, pl = e.type, (e.payload or {})
        if t in ("demo_request", "contact_sales"):
            last_demo = e
        elif t == "meeting_scheduled":
            last_meeting_sched = e
        elif t == "call_logged":
            last_out_channel = "call"
            if pl.get("outcome") == "connected":
                last_connected = e
        elif t == "email_sent":
            last_out_channel = "email"
            if pl.get("template") == "group_demo":
                group_demo_sent = e
        elif t == "meeting_held":
            last_meeting_held, proposal_after_meeting = e, False
        elif t in ("proposal_sent", "contract_sent") and last_meeting_held:
            proposal_after_meeting = True
        elif t == "meeting_no_show":
            last_no_show = e
        elif t == "email_replied":
            last_reply = e
        elif t == "trial_signup":
            last_trial = e
        elif t == "page_view":
            cat = pl.get("page_category")
            if cat == "pricing" and age_hours(now, e.ts) <= w.pricing_hours:
                pricing_72 += 1
            elif cat == "competitor_compare":
                last_competitor = e

    def after_out(e):
        return e is not None and (last_out is None or e.ts > last_out)

    f["demo_recent"] = (last_demo is not None and age_hours(now, last_demo.ts) <= w.demo_hours
                        and not (last_meeting_sched and last_meeting_sched.ts > last_demo.ts)
                        and not (last_connected and last_connected.ts > last_demo.ts))
    f["demo_event"] = last_demo
    reply_cls = reply_class(last_reply.payload, cfg) if last_reply else None
    f["reply_cls"] = reply_cls if after_out(last_reply) else None
    f["reply_pricing"] = (f["reply_cls"] == "positive_intent"
                          and has_pricing_terms((last_reply.payload or {}).get("body"), cfg))
    f["pricing_72"] = pricing_72
    f["no_contact_48h"] = last_out is None or age_hours(now, last_out) >= w.no_contact_hours
    f["trial_recent"] = last_trial is not None and age_days(now, last_trial.ts) <= w.trial_days and after_out(last_trial)
    f["meeting_no_next_step"] = last_meeting_held is not None and not proposal_after_meeting and not (
        last_meeting_sched and last_meeting_sched.ts > last_meeting_held.ts)
    f["no_show_pending"] = (last_no_show is not None and after_out(last_no_show)
                            and not (last_meeting_sched and last_meeting_sched.ts > last_no_show.ts))
    f["competitor_recent"] = (last_competitor is not None and age_days(now, last_competitor.ts) <= w.competitor_days
                              and after_out(last_competitor))
    f["group_demo_sent"] = group_demo_sent is not None and age_days(now, group_demo_sent.ts) <= 14
    f["last_out_channel"] = last_out_channel
    f["inactive_30d"] = (metrics.get("days_since_last_inbound") or 0) >= w.inactive_days
    return f


def _matches(rule_id: str, f: dict, stage: str) -> str | None:
    """Return a reason string if the rule triggers."""
    if rule_id == "N1":
        return "Fake-lead score above quarantine threshold" if f["fake"] else None
    if f["fake"]:
        return None
    if rule_id == "N2" and f["demo_recent"]:
        return f"{f['demo_event'].type.replace('_', ' ').capitalize()} {_fmt(f['_age_demo'])} ago; no meeting booked yet"
    if rule_id == "N3" and f["reply_pricing"]:
        return "Prospect replied asking about pricing/budget"
    if rule_id == "N4" and f["pricing_72"] >= 3 and f["no_contact_48h"]:
        return f"{f['pricing_72']} pricing-page visits in 72h and no rep contact in 48h"
    if rule_id == "N5" and f["trial_recent"]:
        return "New trial signup"
    if rule_id == "N6" and f["meeting_no_next_step"] and stage in ("meeting", "qualified", "engaged"):
        return "Meeting held but no proposal or follow-up meeting yet"
    if rule_id == "N7" and f["is_stalled"] and stage in ("proposal", "negotiation"):
        return f"Deal stalled at {stage}"
    if rule_id == "N8" and f["streak"] >= 3 and f["last_out_channel"] == "email":
        return f"{f['streak']} emails unanswered"
    if rule_id == "N9" and f["no_show_pending"]:
        return "Prospect missed the scheduled meeting"
    if rule_id == "N10" and f["competitor_recent"]:
        return "Prospect is comparing competitors"
    if rule_id == "N11" and f["buying_committee"] and not f["group_demo_sent"] and stage not in ("negotiation",):
        return "Several stakeholders from the account are active"
    if rule_id == "N12" and not f["contacted"] and stage in ("new", "engaged", "qualified"):
        return "New lead not yet contacted"
    if rule_id == "N13" and f["grade"] == "D" and f["inactive_30d"] and stage not in ("nurture",):
        return f"Grade D and inactive for {f['days_since_inbound']:.0f}d"
    if rule_id == "N14" and f["reply_cls"] == "objection":
        return "Prospect raised an objection"
    if rule_id == "N15":
        return "Keep the conversation warm"
    return None


def recommend(stage: str, p: Profile, score: ScoreResult, metrics: dict, stall: dict, events: list[Event], now,
              cfg) -> list[dict]:
    if stage in ("won", "lost") or (stage == "disqualified" and p.fake_status != "fake"):
        return []
    f = build_facts(stage, p, score, metrics, stall, events, now, cfg)
    f["_age_demo"] = age_hours(now, f["demo_event"].ts) if f.get("demo_event") else 0
    out: list[dict] = []
    sla = cfg.assignment.reassignment.first_touch_sla_minutes
    for rule in cfg.nba.rules:
        reason = _matches(rule["id"], f, stage)
        if not reason:
            continue
        due = rule["due_minutes"] if rule["due_minutes"] is not None else sla[score.grade]
        out.append({"rule_id": rule["id"], "action": rule["action"], "channel": rule["channel"], "due_minutes": due,
                    "urgency": rule["urgency"], "reason": reason, "template": rule["template"],
                    "completion": dict(rule.get("completion") or {})})
        if len(out) == 3 or rule["id"] == "N1":
            break
    return out
