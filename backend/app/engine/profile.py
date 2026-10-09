"""Lead profile as a fold over profile-affecting events (pure). Survivorship: most recent non-null wins."""
from __future__ import annotations

import re

from .normalize import normalize_capture
from .types import Event, Profile

PROFILE_EVENT_TYPES = {"lead_created", "lead_enriched", "quality_assessed", "quality_cleared", "lead_merged",
                       "email_replied"}

_IDENTITY_FIELDS = ("email", "email_norm", "phone_e164", "phone_valid", "name", "first_name", "last_name", "company",
                    "company_norm", "domain", "is_free_mail", "title", "seniority", "country", "region")

_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m)?\b|budget (?:of|is|around|about)?\s*~?\$?(\d[\d,]*)\s?(k|m)?",
                    re.IGNORECASE)
_SEATS = re.compile(r"(\d{1,5})\s+(?:seats|users|licen[cs]es)", re.IGNORECASE)


def parse_budget(text: str | None) -> float | None:
    if not text:
        return None
    m = _MONEY.search(text)
    if not m:
        return None
    num = m.group(1) or m.group(3)
    unit = (m.group(2) or m.group(4) or "").lower()
    try:
        value = float(num.replace(",", ""))
    except (TypeError, ValueError):
        return None
    if unit == "k":
        value *= 1_000
    elif unit == "m":
        value *= 1_000_000
    return value if value >= 500 else None


def parse_seats(text: str | None) -> int | None:
    if not text:
        return None
    m = _SEATS.search(text)
    return int(m.group(1)) if m else None


def _disqualifier(p: Profile, cfg) -> str | None:
    dq = cfg.scoring.penalties.disqualifier
    title = (p.title or "").lower()
    for pattern in dq.title_patterns:
        if re.search(pattern, title):
            return "student_or_job_seeker"
    if p.domain and p.domain in dq.competitor_domains:
        return "competitor_domain"
    return None


def apply_profile_event(p: Profile, e: Event, cfg) -> Profile:
    """Mutates and returns p (callers pass a copy they own)."""
    t = e.type
    pl = e.payload or {}
    if t == "lead_created":
        ident = normalize_capture(pl, cfg)
        first = p.created_at is None
        # Fields derived from an input only count as "non-null" when that input was supplied.
        derived_from = {"seniority": "title", "region": "country", "is_free_mail": "email", "email_norm": "email",
                        "phone_valid": "phone"}
        for f in _IDENTITY_FIELDS:
            v = ident.get(f)
            src = derived_from.get(f)
            if src and not pl.get(src) and not first:
                continue
            if v is not None and (first or v != ""):
                setattr(p, f, v)
        if ident.get("email") and ident["email"] not in p.emails:
            p.emails.append(ident["email"])
        if first:
            p.created_at = e.ts
            p.created_event_id = e.event_id
            p.source_primary = e.source
            p.capture_method = pl.get("capture_method")
            p.ip = pl.get("ip")
        if e.source and e.source not in p.sources:
            p.sources.append(e.source)
        if pl.get("budget"):
            p.budget = float(pl["budget"])
        if pl.get("seats"):
            p.seats = int(pl["seats"])
        if pl.get("merged_from") and pl["merged_from"] not in p.merged_ids:
            p.merged_ids.append(pl["merged_from"])
        p.disqualifier = _disqualifier(p, cfg)
    elif t == "lead_enriched":
        p.account_id = pl.get("account_id") or p.account_id
        if pl.get("found"):
            p.enriched = True
            p.enriched_event_id = e.event_id
            p.employees = pl.get("employees")
            p.employee_band = pl.get("employee_band")
            p.industry = pl.get("industry")
            p.revenue_band = pl.get("revenue_band")
            p.hq_country = pl.get("hq_country")
            p.tech_stack = list(pl.get("tech_stack") or [])
            p.funding_stage = pl.get("funding_stage")
    elif t == "quality_assessed":
        if not p.quality_reviewed:
            p.fake_score = float(pl.get("fake_score", 0))
            p.fake_status = pl.get("status", "clean")
            p.fake_signals = list(pl.get("signals") or [])
            p.quality_event_id = e.event_id
    elif t == "quality_cleared":
        p.quality_reviewed = True
        p.fake_status = "clean"
        p.quality_event_id = e.event_id
    elif t == "lead_merged":
        mid = pl.get("merged_id")
        if mid and mid not in p.merged_ids:
            p.merged_ids.append(mid)
    elif t == "email_replied":
        body = pl.get("body")
        b = parse_budget(body)
        if b:
            p.budget = b
        s = parse_seats(body)
        if s:
            p.seats = s
    return p


def build_profile(events: list[Event], cfg, lead_id: str | None = None) -> Profile:
    p = Profile(lead_id=lead_id)
    for e in events:
        if e.type in PROFILE_EVENT_TYPES:
            apply_profile_event(p, e, cfg)
    return p
