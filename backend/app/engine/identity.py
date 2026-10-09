"""Identity resolution / dedupe (pure). Blocking keys + rule-based match confidence."""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz.distance import JaroWinkler

from .types import Profile


def identity_of(p: Profile | dict) -> dict:
    if isinstance(p, dict):
        return p
    return {"email_norm": p.email_norm, "phone_e164": p.phone_e164, "name": p.name, "first_name": p.first_name,
            "last_name": p.last_name, "domain": p.domain, "is_free_mail": p.is_free_mail,
            "company_norm": p.company_norm}


def blocking_keys(ident: dict) -> list[tuple]:
    """Any shared key makes two records a candidate pair."""
    keys: list[tuple] = []
    if ident.get("email_norm"):
        keys.append(("email", ident["email_norm"]))
    if ident.get("phone_e164"):
        keys.append(("phone", ident["phone_e164"]))
    last = (ident.get("last_name") or "").lower()
    first = (ident.get("first_name") or "").lower()
    if ident.get("domain") and last and not ident.get("is_free_mail"):
        keys.append(("domain_last", ident["domain"], last))
    if ident.get("company_norm") and last and first:
        keys.append(("company_name", ident["company_norm"], first[0] + last))
    return keys


def name_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return JaroWinkler.similarity(a.lower(), b.lower())


def match_confidence(a: dict, b: dict, cfg) -> tuple[float, list[str]]:
    """Highest-confidence rule that matches the pair, with the keys that matched."""
    rules = cfg.quality.dedupe.rules
    if a.get("email_norm") and a.get("email_norm") == b.get("email_norm"):
        return float(rules.same_email), ["email_norm"]
    best, keys = 0.0, []
    jw = name_similarity(a.get("name"), b.get("name"))
    same_phone = bool(a.get("phone_e164")) and a.get("phone_e164") == b.get("phone_e164")
    candidates = []
    if same_phone and jw >= rules.phone_and_name.min_jw:
        candidates.append((rules.phone_and_name.confidence, ["phone_e164", f"name_jw={jw:.2f}"]))
    if (a.get("domain") and a.get("domain") == b.get("domain") and not a.get("is_free_mail")
            and jw >= rules.domain_and_name.min_jw):
        candidates.append((rules.domain_and_name.confidence, ["domain", f"name_jw={jw:.2f}"]))
    if a.get("company_norm") and a.get("company_norm") == b.get("company_norm") and jw >= rules.company_and_name.min_jw:
        candidates.append((rules.company_and_name.confidence, ["company_norm", f"name_jw={jw:.2f}"]))
    if same_phone:
        candidates.append((rules.phone_only, ["phone_e164"]))
    for conf, k in candidates:
        if conf > best:
            best, keys = float(conf), k
    return best, keys


@dataclass
class Resolution:
    action: str                    # merge | review | new
    lead_id: str | None = None
    confidence: float = 0.0
    match_keys: list = field(default_factory=list)


def resolve(ident: dict, candidates: list[tuple[str, dict]], cfg) -> Resolution:
    """Pick the best existing match. Ties go to the oldest lead id (survivor rule: oldest survives)."""
    best = Resolution("new")
    for lead_id, other in sorted(candidates, key=lambda c: _lead_order(c[0])):
        conf, keys = match_confidence(ident, other, cfg)
        if conf > best.confidence:
            best = Resolution("new", lead_id, conf, keys)
    th = cfg.quality.dedupe
    if best.confidence >= th.auto_merge:
        best.action = "merge"
    elif best.confidence >= th.review:
        best.action = "review"
    else:
        best = Resolution("new")
    return best


def _lead_order(lead_id: str) -> tuple:
    digits = "".join(ch for ch in lead_id if ch.isdigit())
    return (int(digits) if digits else 0, lead_id)
