"""Normalization of captured identity fields (pure)."""
from __future__ import annotations

import re
from functools import lru_cache

import phonenumbers

_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]")
_URL_PREFIX = re.compile(r"^(https?://)?(www\.)?")


def normalize_email(raw: str | None, cfg) -> tuple[str | None, str | None, bool]:
    """Return (email_norm, domain, is_free_mail).

    Lowercase + trim; strip "+tag" from the local part (plus-addressing); for gmail/googlemail also strip dots.
    """
    if not raw:
        return None, None, False
    e = raw.strip().lower()
    if "@" not in e:
        return None, None, False
    local, _, domain = e.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in cfg.derived.gmail:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local or "." not in domain:
        return None, domain or None, False
    return f"{local}@{domain}", domain, domain in cfg.derived.free_mail


@lru_cache(maxsize=4096)
def normalize_phone(raw: str | None, country: str | None) -> tuple[str | None, bool]:
    """Return (e164, valid). Invalid or unparseable numbers return (None, False)."""
    if not raw:
        return None, False
    try:
        num = phonenumbers.parse(raw, (country or "US").upper())
    except phonenumbers.NumberParseException:
        return None, False
    if not phonenumbers.is_valid_number(num):
        return None, False
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164), True


def normalize_name(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (full, first, last): trim, collapse spaces, title case."""
    if not raw or not raw.strip():
        return None, None, None
    full = _WS.sub(" ", raw.strip()).title()
    parts = full.split(" ")
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None
    return full, first, last


def normalize_company(raw: str | None, cfg) -> str | None:
    """Lowercase, strip punctuation and trailing legal suffixes (inc, llc, ltd, pvt, gmbh, corp, co...)."""
    if not raw:
        return None
    s = _NON_WORD.sub(" ", raw.lower())
    tokens = s.split()
    while tokens and tokens[-1] in cfg.derived.legal_suffixes:
        tokens.pop()
    return " ".join(tokens) or None


def domain_from_website(website: str | None) -> str | None:
    if not website:
        return None
    d = _URL_PREFIX.sub("", website.strip().lower()).split("/")[0]
    return d or None


def seniority_from_title(title: str | None, cfg) -> str:
    if not title:
        return "unknown"
    t = title.lower()
    for level, pattern in _compiled_seniority(cfg):
        if pattern.search(t):
            return level
    return "unknown"


_SENIORITY_CACHE: dict[int, list] = {}


def _compiled_seniority(cfg) -> list:
    key = id(cfg.scoring.seniority_patterns)
    if key not in _SENIORITY_CACHE:
        _SENIORITY_CACHE[key] = [(lvl, re.compile(p)) for lvl, p in cfg.scoring.seniority_patterns]
    return _SENIORITY_CACHE[key]


def region_for_country(country: str | None, cfg) -> str | None:
    if not country:
        return None
    return cfg.derived.country_region.get(country.upper())


def normalize_capture(payload: dict, cfg) -> dict:
    """Normalize a lead_created payload into identity fields."""
    country = (payload.get("country") or "").upper() or None
    email_norm, email_domain, is_free = normalize_email(payload.get("email"), cfg)
    phone, phone_valid = normalize_phone(payload.get("phone"), country)
    full, first, last = normalize_name(payload.get("name"))
    company_norm = normalize_company(payload.get("company"), cfg)
    domain = email_domain if (email_domain and not is_free) else domain_from_website(payload.get("website"))
    return {
        "email": (payload.get("email") or "").strip() or None,
        "email_norm": email_norm,
        "email_domain": email_domain,
        "is_free_mail": is_free,
        "phone_e164": phone,
        "phone_valid": phone_valid if payload.get("phone") else None,
        "name": full,
        "first_name": first,
        "last_name": last,
        "company": (payload.get("company") or "").strip() or None,
        "company_norm": company_norm,
        "domain": domain,
        "title": (payload.get("title") or "").strip() or None,
        "seniority": seniority_from_title(payload.get("title"), cfg),
        "country": country,
        "region": region_for_country(country, cfg),
    }
