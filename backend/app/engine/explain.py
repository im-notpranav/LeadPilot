"""Explanations: diff two factor vectors into contributions that sum exactly to the score delta (pure).

Fit / penalty / clamp contributions are plain value differences. Engagement and intent are saturated
(cap * (1 - e^(-raw/k))), so their contributions are allocated on the raw scale using the secant slope
of the saturation curve: delta_i = slope * delta_raw_i, slope = dS / dRaw. A new signal therefore gets
credit for what it added, and older signals are only charged for their own decay.
"""
from __future__ import annotations

from .scoring import SIGNAL_LABELS, saturate_slope
from .types import Factor

CATEGORY_LABELS = {"fit": "Fit", "engagement": "Engagement", "intent": "Intent", "penalty": "Penalty",
                   "clamp": "Clamp", "merge": "Merge", "minor": "Minor"}

SUMMARY_PHRASES = {
    "intent.demo_request": "requested a demo",
    "intent.contact_sales": "asked to talk to sales",
    "intent.trial_signup": "signed up for a trial",
    "intent.proposal_viewed": "viewed the proposal",
    "intent.positive_reply_intent": "replied with buying intent",
    "intent.competitor_compare": "compared competitors",
    "intent.enterprise_plan_view": "looked at the enterprise plan",
    "intent.case_study_or_roi": "read case studies / ROI",
    "intent.buying_committee": "a buying committee formed",
    "intent.intent_burst_bonus": "an intent burst",
    "engagement.email_replied": "replied to an email",
    "engagement.meeting_held": "held a meeting",
    "engagement.call_connected": "took a call",
    "engagement.webinar_attended": "attended a webinar",
    "engagement.content_download": "downloaded content",
    "engagement.email_clicked": "clicked an email",
    "engagement.form_submit": "submitted a form",
    "engagement.high_intent_form": "filled a high-intent form",
    "engagement.page_view_generic": "browsed the website",
    "engagement.badge_scan": "was scanned at a trade show",
    "penalty.staleness": "has gone quiet",
    "penalty.unanswered_streak": "ignored follow-ups",
    "penalty.negative_reply": "replied negatively",
    "penalty.meeting_no_show": "missed a meeting",
    "penalty.email_bounced": "email bounced",
    "penalty.unsubscribed": "unsubscribed",
    "penalty.quality_risk": "was flagged as a possible fake",
}


def diff(prev: dict | None, new: dict, cfg) -> list[dict]:
    """All non-zero contributions (major ones individually, small ones rolled into 'minor'), sorted by |delta|."""
    prev = prev or {}
    raw_contribs: list[tuple[str, float, Factor | None, Factor | None]] = []

    for key in sorted(set(prev) | set(new)):
        old_f, new_f = prev.get(key), new.get(key)
        cat = (new_f or old_f).category
        if cat in ("engagement", "intent"):
            continue
        d = (new_f.value if new_f else 0.0) - (old_f.value if old_f else 0.0)
        if abs(d) > 1e-9:
            raw_contribs.append((key, d, old_f, new_f))

    for cat in ("engagement", "intent"):
        keys = sorted(k for k in set(prev) | set(new) if (new.get(k) or prev.get(k)).category == cat)
        if not keys:
            continue
        s_old = sum(prev[k].value for k in keys if k in prev)
        s_new = sum(new[k].value for k in keys if k in new)
        r_old = sum(prev[k].raw for k in keys if k in prev)
        r_new = sum(new[k].raw for k in keys if k in new)
        d_r = r_new - r_old
        sat = cfg.scoring.saturation[cat]
        slope = (s_new - s_old) / d_r if abs(d_r) > 1e-6 else saturate_slope(r_new, sat.cap, sat.k)
        parts = []
        for k in keys:
            d_raw = (new[k].raw if k in new else 0.0) - (prev[k].raw if k in prev else 0.0)
            if abs(d_raw) > 1e-12:
                parts.append([k, slope * d_raw, prev.get(k), new.get(k)])
        residual = (s_new - s_old) - sum(p[1] for p in parts)
        if parts:
            biggest = max(parts, key=lambda p: abs(p[1]))
            biggest[1] += residual
        elif abs(residual) > 1e-9:
            parts.append([keys[0], residual, prev.get(keys[0]), new.get(keys[0])])
        for k, d, o, n in parts:
            if abs(d) > 1e-9:
                raw_contribs.append((k, d, o, n))

    min_display = cfg.scoring.min_display_delta
    major, minor = [], []
    for key, d, o, n in raw_contribs:
        c = _contribution(key, d, o, n)
        (major if abs(d) >= min_display else minor).append(c)
    major.sort(key=lambda c: (-abs(c["delta"]), c["key"]))
    if minor:
        total = sum(c["delta"] for c in minor)
        if abs(total) > 1e-9:
            major.append({"key": "minor", "category": "minor", "delta": total, "evidence": [],
                          "reason": f"{len(minor)} small changes (time decay)",
                          "text": f"{total:+.1f} Minor · {len(minor)} small changes (time decay)",
                          "parts": [{"key": c["key"], "delta": c["delta"]} for c in minor]})
    return major


def _contribution(key: str, delta: float, old: Factor | None, new: Factor | None) -> dict:
    f = new or old
    cat = f.category
    reason = _reason(key, delta, old, new)
    return {"key": key, "category": cat, "delta": delta, "old": old.value if old else 0.0,
            "new": new.value if new else 0.0, "reason": reason, "evidence": list((new or old).evidence[-5:]),
            "text": f"{delta:+.1f} {CATEGORY_LABELS.get(cat, cat)} · {reason}"}


def _reason(key: str, delta: float, old: Factor | None, new: Factor | None) -> str:
    cat = (new or old).category
    label = (new or old).label or key
    if cat in ("engagement", "intent"):
        if new and (not old or new.count > old.count):
            return new.reason
        if new and old and new.count < old.count:
            return f"Older {label}s aged out of the repeat window"
        if new and old and delta < 0:
            hl = new.half_life
            return f"{label[0].upper() + label[1:]} activity aged" + (f" (half-life {hl:g}d)" if hl else "")
        if old and not new:
            return f"{label[0].upper() + label[1:]} expired"
        return new.reason if new else label
    if cat == "penalty":
        if new and not old:
            return new.reason
        if old and not new:
            return f"{label} cleared"
        return new.reason
    if cat == "fit":
        return (new.reason if new else f"{label} removed")
    return (new or old).reason


def merge_contribution(contribs: list[dict], merged_id: str, match_desc: str) -> list[dict]:
    """Collapse a merge step's contributions into a single 'merge' contribution (sum preserved)."""
    total = sum(c["delta"] for c in contribs)
    by_cat: dict[str, float] = {}
    for c in contribs:
        cat = c["category"] if c["category"] != "minor" else "decay"
        by_cat[cat] = by_cat.get(cat, 0.0) + c["delta"]
    detail = ", ".join(f"{v:+.1f} {k}" for k, v in sorted(by_cat.items(), key=lambda kv: -abs(kv[1])) if abs(v) >= 0.05)
    reason = f"Merged duplicate {merged_id} ({match_desc})" + (f": {detail} from its history" if detail else "")
    return [{"key": "merge", "category": "merge", "delta": total, "evidence": [], "reason": reason,
             "text": f"{total:+.1f} Merge · {reason}", "parts": contribs}]


def summary(old: float, new: float, contribs: list[dict], event_type: str | None, new_factors: dict) -> str:
    o, n = round(old), round(new)
    if not contribs:
        why = f"{event_type.replace('_', ' ')} has no direct score impact" if event_type else "no material change"
        return f"Score unchanged at {n}: {why}."
    if abs(new - old) < 0.05:
        return f"Score steady at {n}: {_phrase(contribs[0], new_factors)} (net {new - old:+.2f})."
    phrases = []
    for c in contribs[:3]:
        if c["key"] in ("minor",):
            continue
        phrases.append(_phrase(c, new_factors))
        if len(phrases) == 2:
            break
    head = f"Score {o} -> {n}" if o != n else f"Score {n} ({new - old:+.1f})"
    return f"{head}: {' and '.join(p for p in phrases if p) or 'time decay'}."


def _phrase(c: dict, new_factors: dict) -> str:
    key = c["key"]
    if c["category"] == "merge":
        r = c["reason"].split(":")[0]
        return r[0].lower() + r[1:]
    if c["category"] == "fit":
        return f"{c['reason'].lower()} (fit)"
    f = new_factors.get(key)
    if c["delta"] > 0 and key in SUMMARY_PHRASES and c["category"] != "penalty":
        if key == "intent.pricing_view" and f:
            return f"visited pricing {f.count}x"
        return SUMMARY_PHRASES[key]
    if key == "intent.pricing_view" and c["delta"] > 0 and f:
        return f"visited pricing {f.count}x"
    if c["category"] == "penalty":
        if c["delta"] < 0:
            return SUMMARY_PHRASES.get(key, c["reason"].lower())
        return f"{c['reason'].lower()}"
    if c["delta"] < 0:
        sig = key.split(".", 1)[-1]
        return f"{SIGNAL_LABELS.get(sig, sig)} activity aging"
    sig = key.split(".", 1)[-1]
    return f"new {SIGNAL_LABELS.get(sig, sig)}"
