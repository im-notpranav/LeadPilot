"""Intent detection: deterministic reply classifier, intent level, active intent signals (pure)."""
from __future__ import annotations

import os
from typing import Protocol

from .types import Event, age_hours

REPLY_CLASSES = ("positive_intent", "neutral", "objection", "negative", "out_of_office")

_CLASS_CACHE: dict[tuple, str] = {}


def _contains_any(text: str, terms) -> bool:
    return any(term in text for term in terms)


class ReplyClassifier(Protocol):
    def classify(self, body: str | None) -> str: ...


class KeywordReplyClassifier:
    """Keyword lists live in scoring.yaml: reply_classifier."""

    def __init__(self, cfg):
        self.rc = cfg.scoring.reply_classifier

    def classify(self, body: str | None) -> str:
        if not body:
            return "neutral"
        key = (id(self.rc), body)
        hit = _CLASS_CACHE.get(key)
        if hit:
            return hit
        text = " " + body.lower() + " "
        result = "neutral"
        for cls in self.rc.order:
            if _contains_any(text, self.rc[cls]):
                result = cls
                break
        _CLASS_CACHE[key] = result
        return result


class LLMReplyClassifier:
    """Optional, behind USE_LLM=true. Falls back to keywords; core logic never depends on it."""

    def __init__(self, cfg):
        self.fallback = KeywordReplyClassifier(cfg)
        self.enabled = os.environ.get("USE_LLM", "false").lower() == "true"

    def classify(self, body: str | None) -> str:
        return self.fallback.classify(body)


def classify_reply(body: str | None, cfg) -> str:
    return KeywordReplyClassifier(cfg).classify(body)


def reply_class(payload: dict | None, cfg) -> str:
    """Class of an email_replied payload. Replies the inbound-email parser marked as automatic (auto-reply
    headers, "Automatic reply:" subjects) are out of office whatever their text says."""
    pl = payload or {}
    return "out_of_office" if pl.get("auto_reply") else classify_reply(pl.get("body"), cfg)


def has_negotiation_terms(body: str | None, cfg) -> bool:
    return bool(body) and _contains_any(" " + body.lower() + " ", cfg.scoring.reply_classifier.negotiation)


def has_pricing_terms(body: str | None, cfg) -> bool:
    return bool(body) and _contains_any(body.lower(), cfg.scoring.reply_classifier.pricing_terms)


def intent_level(intent_points: float, events: list[Event], now, cfg) -> str:
    lv = cfg.scoring.intent_levels
    for e in reversed(events):
        if age_hours(now, e.ts) > lv.hot_recent_hours:
            break
        if e.type in lv.hot_signals and e.ts <= now:
            return "hot"
    th = lv.thresholds
    if intent_points >= th.hot:
        return "hot"
    if intent_points >= th.high:
        return "high"
    if intent_points >= th.medium:
        return "medium"
    if intent_points >= th.low:
        return "low"
    return "none"


def intent_level_index(level: str, cfg) -> int:
    return cfg.scoring.intent_levels.index.get(level, 0)


def active_intent_signals(intent_factors: dict, events: list[Event], now, cfg) -> list[str]:
    """Human-readable named signals, e.g. ["pricing_page_x3_48h", "demo_request", "buying_committee"]."""
    window = cfg.scoring.intent_levels.active_window_hours
    out: list[str] = []
    pricing_48 = pricing_7d = 0
    seen: set[str] = set()
    for e in events:
        if e.ts > now:
            continue
        h = age_hours(now, e.ts)
        if h > window:
            continue
        if e.type == "page_view" and (e.payload or {}).get("page_category") == "pricing":
            pricing_7d += 1
            if h <= 48:
                pricing_48 += 1
        elif e.type in ("demo_request", "contact_sales", "trial_signup", "proposal_viewed"):
            seen.add(e.type)
        elif e.type == "page_view" and (e.payload or {}).get("page_category") == "competitor_compare":
            seen.add("competitor_compare")
        elif e.type == "page_view" and (e.payload or {}).get("page_category") == "enterprise_plan":
            seen.add("enterprise_plan")
    if pricing_48 >= 2:
        out.append(f"pricing_page_x{pricing_48}_48h")
    elif pricing_7d >= 1:
        out.append(f"pricing_page_x{pricing_7d}_7d")
    for name in ("demo_request", "contact_sales", "trial_signup", "proposal_viewed", "competitor_compare", "enterprise_plan"):
        if name in seen:
            out.append(name)
    if "intent.positive_reply_intent" in intent_factors:
        out.append("positive_reply")
    if "intent.buying_committee" in intent_factors:
        out.append("buying_committee")
    if "intent.intent_burst_bonus" in intent_factors:
        out.append("intent_burst")
    return out
