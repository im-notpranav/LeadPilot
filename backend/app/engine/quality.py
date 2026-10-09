"""Fake / low-quality lead detection (pure). Free-mail is a fit penalty, not a fake signal."""
from __future__ import annotations

import re

_VOWELS = set("aeiou")
_REPEATED_DIGITS = re.compile(r"(\d)\1{6,}")


def _test_pattern_hit(text: str, patterns: list[str]) -> str | None:
    t = text.lower()
    for p in patterns:
        if re.search(rf"(^|[^a-z]){re.escape(p)}", t):
            return p
    return None


def is_gibberish(name: str | None, cfg) -> str | None:
    if not name:
        return None
    g = cfg.quality.gibberish
    letters = "".join(ch for ch in name.lower() if ch.isalpha())
    if len(letters) < 4:
        return None
    ratio = sum(ch in _VOWELS for ch in letters) / len(letters)
    if ratio < g.min_vowel_ratio or ratio > g.max_vowel_ratio:
        return f"vowel ratio {ratio:.2f}"
    if re.search(r"([a-z])\1{%d,}" % (g.repeated_chars - 1), letters):
        return "repeated characters"
    for run in map(str, g.keyboard_runs):
        if run in letters:
            return f"keyboard run '{run}'"
    return None


def assess(ident: dict, payload: dict, ctx: dict, cfg) -> dict:
    """Return {fake_score, status, signals:[{key, weight, detail}]}.

    ctx: ip_submissions_last_hour (int), mx_valid (bool|None), ip_country (str|None), disposable (bool)
    """
    q = cfg.quality
    w = q.signals
    signals: list[dict] = []

    def hit(key: str, detail: str) -> None:
        signals.append({"key": key, "weight": w[key], "detail": detail})

    email = (payload.get("email") or "").lower()
    local = email.split("@")[0] if "@" in email else email
    domain = ident.get("email_domain") or ""
    if ctx.get("disposable"):
        hit("disposable_email", f"disposable domain {domain}")
    if ctx.get("mx_valid") is False:
        hit("no_mx", f"no MX record for {domain}")
    for field_name in ("name", "email", "company"):
        p = _test_pattern_hit(payload.get(field_name) or "", q.test_patterns)
        if p:
            hit("test_pattern", f"'{p}' in {field_name}")
            break
    n_ip = ctx.get("ip_submissions_last_hour", 0)
    if n_ip > q.ip_velocity.max_per_hour:
        hit("ip_velocity", f"{n_ip} submissions/hour from {payload.get('ip')}")
    g = is_gibberish(payload.get("name"), cfg)
    if g:
        hit("gibberish_name", g)
    fill = payload.get("form_fill_seconds")
    if fill is not None and fill < q.fast_form_seconds:
        hit("fast_form", f"form filled in {fill}s")
    raw_phone = payload.get("phone")
    if raw_phone:
        digits = "".join(ch for ch in raw_phone if ch.isdigit())
        if _REPEATED_DIGITS.search(digits) or len(set(digits[-10:])) <= 2:
            hit("invalid_phone", "repeated digits")
        elif not ident.get("phone_valid"):
            hit("invalid_phone", "number does not parse")
    ip_country = ctx.get("ip_country")
    if ip_country and ident.get("country") and ip_country != ident["country"]:
        hit("ip_country_mismatch", f"IP in {ip_country}, stated {ident['country']}")
    if local in q.role_mailboxes:
        hit("role_mailbox", f"role mailbox {local}@")
    score = min(100, sum(s["weight"] for s in signals))
    return {"fake_score": score, "status": status_for(score, cfg), "signals": signals}


def status_for(score: float, cfg) -> str:
    th = cfg.quality.thresholds
    if score >= th.fake:
        return "fake"
    if score >= th.suspicious:
        return "suspicious"
    return "clean"
