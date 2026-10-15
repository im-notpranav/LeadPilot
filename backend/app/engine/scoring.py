"""Dynamic lead scoring (pure).

score = clamp(Fit[0..40] + Engagement[0..35] + Intent[0..25] - Penalties, 0, 100)

The score is a pure function of (profile, event history, now, context, config). Each part is a list of
named factors; the explanation of a score change is the diff of two factor vectors (see explain.py).
"""
from __future__ import annotations

import math
from collections import deque

from .intent import active_intent_signals, intent_level, reply_class
from .metrics import is_inbound
from .types import DAY, Event, Factor, LeadContext, Profile, ScoreResult, age_days, age_hours

PAGE_INTENT = {
    "pricing": "pricing_view",
    "case_study": "case_study_or_roi",
    "roi": "case_study_or_roi",
    "competitor_compare": "competitor_compare",
    "enterprise_plan": "enterprise_plan_view",
}
SIMPLE_SIGNALS = {
    "email_opened": ("engagement", "email_opened"),
    "email_clicked": ("engagement", "email_clicked"),
    "content_download": ("engagement", "content_download"),
    "webinar_registered": ("engagement", "webinar_registered"),
    "webinar_attended": ("engagement", "webinar_attended"),
    "meeting_held": ("engagement", "meeting_held"),
    "proposal_viewed": ("intent", "proposal_viewed"),
}
SIGNAL_LABELS = {
    "email_opened": "email open", "email_clicked": "email click", "page_view_generic": "page view",
    "content_download": "content download", "webinar_registered": "webinar registration",
    "webinar_attended": "webinar attended", "email_replied": "email reply", "call_connected": "connected call",
    "meeting_held": "meeting held", "badge_scan": "trade-show badge scan", "form_submit": "form submission",
    "high_intent_form": "high-intent form", "pricing_view": "pricing-page visit",
    "case_study_or_roi": "case study / ROI view", "competitor_compare": "competitor comparison view",
    "enterprise_plan_view": "enterprise plan view", "demo_request": "demo request",
    "contact_sales": "contact-sales request", "trial_signup": "trial signup",
    "positive_reply_intent": "reply with buying intent", "positive_call_intent": "call with buying intent",
    "proposal_viewed": "proposal view",
    "buying_committee": "buying committee", "intent_burst_bonus": "intent burst bonus",
}
FIT_LABELS = {"company_size": "Company size", "industry_icp": "Industry ICP", "seniority": "Seniority",
              "territory_served": "Territory", "business_email": "Business email"}
PENALTY_LABELS = {"staleness": "Staleness", "unanswered_streak": "Unanswered follow-ups",
                  "email_bounced": "Email bounced", "unsubscribed": "Unsubscribed", "meeting_no_show": "Meeting no-show",
                  "negative_reply": "Negative reply", "disqualifier": "Disqualifier", "quality_risk": "Quality risk"}

_SIGNAL_CACHE: dict[tuple, tuple] = {}


def saturate(raw: float, cap: float, k: float) -> float:
    return cap * (1.0 - math.exp(-raw / k)) if raw > 0 else 0.0


def saturate_slope(raw: float, cap: float, k: float) -> float:
    return (cap / k) * math.exp(-max(raw, 0.0) / k)


def grade_for(score: float, cfg) -> str:
    g = cfg.scoring.grades
    if score >= g.A:
        return "A"
    if score >= g.B:
        return "B"
    if score >= g.C:
        return "C"
    return "D"


def event_signals(e: Event, cfg) -> tuple:
    """Signals produced by one event: tuple of (category, signal_key). Memoized on the event (events are immutable
    once processed); the memo is keyed by config identity so a different config recomputes."""
    c = e.cache
    if c is not None and c[0] is cfg:
        return c[1]
    result = _event_signals(e, cfg)
    e.cache = (cfg, result)
    return result


def _event_signals(e: Event, cfg) -> tuple:
    pl = e.payload or {}
    t = e.type
    out: list[tuple[str, str]] = []
    if t == "page_view":
        out.append(("engagement", "page_view_generic"))
        sig = PAGE_INTENT.get(pl.get("page_category"))
        if sig:
            out.append(("intent", sig))
    elif t in SIMPLE_SIGNALS:
        out.append(SIMPLE_SIGNALS[t])
    elif t in ("demo_request", "contact_sales", "trial_signup"):
        out.append(("intent", t))
        out.append(("engagement", "high_intent_form"))
    elif t == "email_replied":
        cls = reply_class(pl, cfg)
        if cls in ("positive_intent", "neutral", "objection"):
            out.append(("engagement", "email_replied"))
        if cls == "positive_intent":
            out.append(("intent", "positive_reply_intent"))
    elif t == "call_logged" and pl.get("outcome") == "connected":
        out.append(("engagement", "call_connected"))
        if pl.get("call_intent") == "positive_intent":       # written into the event by the call analysis
            out.append(("intent", "positive_call_intent"))
    elif t == "lead_created":
        cm = pl.get("capture_method")
        if cm == "badge_scan":
            out.append(("engagement", "badge_scan"))
        elif cm != "cold_import":
            out.append(("engagement", "form_submit"))
    return tuple(out)


_PARAMS_CACHE: dict[int, tuple] = {}


def _signal_params(cfg) -> dict:
    hit = _PARAMS_CACHE.get(id(cfg))
    if hit is not None and hit[0] is cfg:
        return hit[1]
    sc = cfg.scoring
    params = {}
    for cat in ("engagement", "intent"):
        for sig, p in sc[cat].items():
            if "half_life_days" in p:
                params[(cat, sig)] = (p["points"], p["half_life_days"], p.get("repeat_decay", 1.0))
    _PARAMS_CACHE[id(cfg)] = (cfg, params)
    return params


def _fmt_age(hours: float) -> str:
    if hours < 1:
        return f"{max(1, int(hours * 60))}m ago"
    if hours < 48:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------- fit

def fit_factors(p: Profile, cfg) -> list[Factor]:
    f = cfg.scoring.fit
    out: list[Factor] = []
    ev_enr = [p.enriched_event_id] if p.enriched_event_id else []
    ev_cap = [p.created_event_id] if p.created_event_id else []

    if p.employees is None:
        out.append(Factor("fit.company_size", "fit", f.company_size.unknown, "Company size unknown (not enriched)",
                          [], FIT_LABELS["company_size"]))
    else:
        pts, label = 0, ""
        for band in f.company_size.bands:
            if band["max"] is None or p.employees <= band["max"]:
                pts, label = band["points"], band["label"]
                break
        out.append(Factor("fit.company_size", "fit", pts, f"{p.employees:,} employees ({label})", ev_enr,
                          FIT_LABELS["company_size"]))

    if not p.industry:
        out.append(Factor("fit.industry_icp", "fit", f.industry_icp.unknown, "Industry unknown", [],
                          FIT_LABELS["industry_icp"]))
    else:
        pts, tier = f.industry_icp.other, "non-ICP"
        for t in f.industry_icp.tiers:
            if p.industry in t["industries"]:
                pts, tier = t["points"], t["name"]
                break
        out.append(Factor("fit.industry_icp", "fit", pts, f"{p.industry} is {tier}", ev_enr, FIT_LABELS["industry_icp"]))

    pts = f.seniority.get(p.seniority, f.seniority["unknown"])
    out.append(Factor("fit.seniority", "fit", pts,
                      f"{p.title or 'No title'} -> {p.seniority.replace('_', '-')}", ev_cap, FIT_LABELS["seniority"]))

    served = p.region in f.territory_served.served_regions
    out.append(Factor("fit.territory_served", "fit", f.territory_served.points if served else 0,
                      f"{p.region or 'Unknown region'} {'is served' if served else 'is not a served territory'}",
                      ev_cap, FIT_LABELS["territory_served"]))

    business = bool(p.domain) and not p.is_free_mail and bool(p.email_norm)
    out.append(Factor("fit.business_email", "fit", f.business_email.points if business else 0,
                      f"Business email @{p.domain}" if business else "Free-mail or missing business email",
                      ev_cap, FIT_LABELS["business_email"]))
    return out


# ---------------------------------------------------------------- engagement + intent

class _Agg:
    __slots__ = ("raw", "count", "evidence", "last_ts", "recent48", "half_life")

    def __init__(self, half_life):
        self.raw = 0.0
        self.count = 0
        self.evidence: list[str] = []
        self.last_ts = None
        self.recent48 = 0
        self.half_life = half_life


def _signal_aggregates(events: list[Event], now, cfg) -> dict:
    window = cfg.scoring.repeat_window_days * DAY
    params_map = _signal_params(cfg)
    now_s = now.timestamp()
    recent: dict[tuple, deque] = {}
    aggs: dict[tuple, _Agg] = {}
    for e in events:
        sigs = event_signals(e, cfg)
        if not sigs:
            continue
        ts_s = e.ts.timestamp()
        age_s = now_s - ts_s
        for key in sigs:
            points, hl, rd = params_map[key]
            dq = recent.get(key)
            if dq is None:
                dq = recent[key] = deque()
            while dq and dq[0] < ts_s - window:
                dq.popleft()
            k = len(dq) + 1
            dq.append(ts_s)
            pts = points * 0.5 ** ((age_s / DAY) / hl) * rd ** (k - 1)
            agg = aggs.get(key)
            if agg is None:
                agg = aggs[key] = _Agg(hl)
            agg.raw += pts
            agg.count += 1
            agg.evidence.append(e.event_id)
            agg.last_ts = e.ts
            if age_s <= 48 * 3600:
                agg.recent48 += 1
    return aggs


def _signal_reason(sig: str, agg: _Agg, now) -> str:
    label = SIGNAL_LABELS.get(sig, sig)
    last = _fmt_age(age_hours(now, agg.last_ts))
    if agg.count == 1:
        return f"{label[0].upper() + label[1:]} ({last})"
    if agg.recent48 >= 2:
        return f"{_ordinal(agg.recent48)} {label} in 48h (latest {last})"
    return f"{agg.count}x {label} (latest {last})"


def engagement_intent_factors(events: list[Event], now, ctx: LeadContext, cfg):
    sc = cfg.scoring
    aggs = _signal_aggregates(events, now, cfg)
    eng: dict[str, Factor] = {}
    intent: dict[str, Factor] = {}
    for (cat, sig), agg in aggs.items():
        if agg.raw <= 1e-9:
            continue
        f = Factor(f"{cat}.{sig}", cat, 0.0, _signal_reason(sig, agg, now), agg.evidence[-10:],
                   SIGNAL_LABELS.get(sig, sig), raw=agg.raw, count=agg.count, half_life=agg.half_life)
        (eng if cat == "engagement" else intent)[f.key] = f

    # Intent burst bonus: >= min_signals high-intent signals in the trailing window.
    burst = sc.intent.intent_burst_bonus
    hi_ids = []
    for e in events:
        if age_hours(now, e.ts) <= burst.window_hours:
            for cat, sig in event_signals(e, cfg):
                if cat == "intent" and sig in cfg.derived.high_intent:
                    hi_ids.append(e.event_id)
                    break
    if len(hi_ids) >= burst.min_signals:
        intent["intent.intent_burst_bonus"] = Factor(
            "intent.intent_burst_bonus", "intent", 0.0,
            f"{len(hi_ids)} high-intent signals within {burst.window_hours}h (intent burst bonus active)",
            hi_ids[-10:], SIGNAL_LABELS["intent_burst_bonus"], raw=burst.points, count=len(hi_ids))

    # Buying committee: >= N other active leads at the same account in the window.
    bc = sc.intent.buying_committee
    others = {lid for ts, lid in ctx.account_activity if ts <= now and age_days(now, ts) <= bc.window_days}
    if len(others) >= bc.min_other_leads:
        intent["intent.buying_committee"] = Factor(
            "intent.buying_committee", "intent", 0.0,
            f"{len(others)} other people from this account active in {bc.window_days}d",
            sorted(others), SIGNAL_LABELS["buying_committee"], raw=bc.points, count=len(others))

    eng_total = _allocate(eng, sc.saturation.engagement)
    intent_total = _allocate(intent, sc.saturation.intent)
    return eng, intent, eng_total, intent_total


def _allocate(factors: dict, sat) -> float:
    raw = sum(f.raw for f in factors.values())
    total = saturate(raw, sat.cap, sat.k)
    for f in factors.values():
        f.value = total * f.raw / raw if raw > 0 else 0.0
    return total


# ---------------------------------------------------------------- penalties

def penalty_factors(p: Profile, events: list[Event], now, cfg) -> list[Factor]:
    pen = cfg.scoring.penalties
    inbound = cfg.derived.inbound_types
    responses = cfg.derived.response_types
    outbound = cfg.derived.rep_outbound_types
    out: list[Factor] = []

    last_inbound = None
    streak: list[str] = []
    bounced = unsub = None
    negative = None
    no_shows: list[Event] = []
    for e in events:
        if is_inbound(e, cfg):
            last_inbound = e
        if e.type in responses or (e.type == "call_logged" and (e.payload or {}).get("outcome") == "connected"):
            streak = []
        elif e.actor == "rep" and e.type in outbound:
            streak.append(e.event_id)
        if e.type == "email_bounced":
            bounced = e
        elif e.type == "unsubscribed":
            unsub = e
        elif e.type == "meeting_no_show":
            no_shows.append(e)
        elif e.type == "email_replied":
            cls = reply_class(e.payload, cfg)
            if cls == "negative":
                negative = e
            elif cls in ("positive_intent", "neutral"):
                negative = None

    ref = last_inbound.ts if last_inbound else p.created_at
    if ref is not None:
        days = age_days(now, ref)
        extra = math.floor(days - pen.staleness.grace_days)
        if extra > 0:
            v = min(pen.staleness.max, extra * pen.staleness.per_day)
            out.append(Factor("penalty.staleness", "penalty", -v, f"No prospect activity for {int(days)} days",
                              [last_inbound.event_id] if last_inbound else [], PENALTY_LABELS["staleness"],
                              count=int(days)))
    if len(streak) >= pen.unanswered_streak.min_streak:
        out.append(Factor("penalty.unanswered_streak", "penalty", -pen.unanswered_streak.points,
                          f"{len(streak)} follow-ups with no reply", streak[-5:], PENALTY_LABELS["unanswered_streak"],
                          count=len(streak)))
    if bounced:
        out.append(Factor("penalty.email_bounced", "penalty", -pen.email_bounced.points, "Email hard-bounced",
                          [bounced.event_id], PENALTY_LABELS["email_bounced"], count=1))
    if unsub:
        out.append(Factor("penalty.unsubscribed", "penalty", -pen.unsubscribed.points, "Unsubscribed from email",
                          [unsub.event_id], PENALTY_LABELS["unsubscribed"], count=1))
    if no_shows:
        v = sum(pen.meeting_no_show.points * 0.5 ** (age_days(now, e.ts) / pen.meeting_no_show.half_life_days)
                for e in no_shows)
        if v > 1e-6:
            out.append(Factor("penalty.meeting_no_show", "penalty", -v, f"{len(no_shows)} meeting no-show(s)",
                              [e.event_id for e in no_shows], PENALTY_LABELS["meeting_no_show"], count=len(no_shows),
                              half_life=pen.meeting_no_show.half_life_days))
    if negative:
        out.append(Factor("penalty.negative_reply", "penalty", -pen.negative_reply.points,
                          "Reply classified negative", [negative.event_id], PENALTY_LABELS["negative_reply"], count=1))
    if p.disqualifier:
        out.append(Factor("penalty.disqualifier", "penalty", -pen.disqualifier.points,
                          f"Disqualifier: {p.disqualifier.replace('_', ' ')}", [p.created_event_id] if p.created_event_id else [],
                          PENALTY_LABELS["disqualifier"], count=1))
    qr = pen.quality_risk
    if p.fake_score >= qr.threshold and not p.quality_reviewed:
        v = min(qr.max, (p.fake_score - qr.threshold) / qr.divisor)
        if v > 0:
            out.append(Factor("penalty.quality_risk", "penalty", -v, f"Fake-lead risk {int(p.fake_score)}/100",
                              [p.quality_event_id] if p.quality_event_id else [], PENALTY_LABELS["quality_risk"], count=1))
    return out


# ---------------------------------------------------------------- total

def compute_score(p: Profile, events: list[Event], now, ctx: LeadContext, cfg) -> ScoreResult:
    """Full recompute from history. `events` must be sorted by (ts, event_id)."""
    evs = [e for e in events if e.ts <= now]
    if len(evs) > cfg.scoring.max_events:
        evs = evs[-cfg.scoring.max_events:]
    factors: dict[str, Factor] = {}
    fit = 0.0
    for f in fit_factors(p, cfg):
        factors[f.key] = f
        fit += f.value
    eng, intent, eng_total, intent_total = engagement_intent_factors(evs, now, ctx, cfg)
    factors.update(eng)
    factors.update(intent)
    pens = penalty_factors(p, evs, now, cfg)
    pen_total = 0.0
    for f in pens:
        factors[f.key] = f
        pen_total += f.value
    raw = fit + eng_total + intent_total + pen_total
    score = min(100.0, max(0.0, raw))
    if abs(score - raw) > 1e-12:
        factors["clamp"] = Factor("clamp", "clamp", score - raw,
                                  "Score floored at 0" if raw < 0 else "Score capped at 100", [], "Clamp")
    level = intent_level(intent_total, evs, now, cfg)
    return ScoreResult(score=score, grade=grade_for(score, cfg), fit=fit, engagement=eng_total, intent=intent_total,
                       penalties=pen_total, factors=factors, raw_engagement=sum(f.raw for f in eng.values()),
                       raw_intent=sum(f.raw for f in intent.values()), intent_level=level,
                       active_signals=active_intent_signals(intent, evs, now, cfg))
