"""Per-lead engagement metrics, recomputed on every event (pure)."""
from __future__ import annotations

from .types import Event, age_days

# Logged by the rep, but they are the prospect engaging live.
_LIVE_ENGAGEMENT = {"meeting_held"}


def is_inbound(e: Event, cfg) -> bool:
    """Prospect activity that resets staleness / inactivity clocks."""
    t = e.type
    if t == "call_logged":
        return (e.payload or {}).get("outcome") == "connected"
    if t not in cfg["derived"]["inbound_types"]:
        return False
    return e.actor == "prospect" or t in _LIVE_ENGAGEMENT


def engagement_metrics(events: list[Event], now, cfg) -> dict:
    inbound = cfg.derived.inbound_types
    responses = cfg.derived.response_types
    outbound = cfg.derived.rep_outbound_types
    rep_activity = cfg.derived.rep_activity_types

    created = None
    first_outbound = None
    last_inbound = last_outbound = last_rep_activity = None
    last_prospect_in = None          # most recent prospect inbound not yet answered by a rep outbound
    last_rep_out = None              # most recent rep outbound not yet answered by a prospect reply
    reply_response: list[float] = []
    prospect_response: list[float] = []
    streak = 0
    e7 = prev7 = 0
    for e in events:
        if e.ts > now:
            break
        if e.type == "lead_created" and created is None:
            created = e.ts
        is_prospect_in = is_inbound(e, cfg)
        is_rep_out = e.actor == "rep" and e.type in outbound
        if e.actor == "prospect" and not e.derived:
            d = age_days(now, e.ts)
            if d <= 7:
                e7 += 1
            elif d <= 14:
                prev7 += 1
        if is_prospect_in:
            last_inbound = e
            if last_prospect_in is None:
                last_prospect_in = e
        if e.type == "email_replied" and last_rep_out is not None:
            prospect_response.append((e.ts - last_rep_out.ts).total_seconds() / 60)
            last_rep_out = None
        if is_rep_out:
            if first_outbound is None:
                first_outbound = e
            if last_prospect_in is not None:
                reply_response.append((e.ts - last_prospect_in.ts).total_seconds() / 60)
                last_prospect_in = None
            last_outbound = e
            last_rep_out = e
        if e.actor == "rep" and e.type in rep_activity:
            last_rep_activity = e
        if e.type in responses or (e.type == "call_logged" and (e.payload or {}).get("outcome") == "connected"):
            streak = 0
        elif is_rep_out:
            streak += 1

    ref_in = last_inbound.ts if last_inbound else created
    return {
        "created_at": created,
        "first_response_at": first_outbound.ts if first_outbound else None,
        "first_response_minutes": ((first_outbound.ts - created).total_seconds() / 60) if (first_outbound and created) else None,
        "first_response_rep_id": first_outbound.rep_id if first_outbound else None,
        "reply_response_minutes": reply_response,
        "prospect_response_minutes": prospect_response,
        "engagement_7d": e7,
        "engagement_prev_7d": prev7,
        "engagement_velocity": (e7 / prev7) if prev7 else None,
        "unanswered_outbound_streak": streak,
        "last_inbound_at": last_inbound.ts if last_inbound else None,
        "last_inbound_event_id": last_inbound.event_id if last_inbound else None,
        "last_outbound_at": last_outbound.ts if last_outbound else None,
        "last_rep_activity_at": last_rep_activity.ts if last_rep_activity else None,
        "days_since_last_inbound": age_days(now, ref_in) if ref_in else None,
        "days_since_last_outbound": age_days(now, last_outbound.ts) if last_outbound else None,
    }
