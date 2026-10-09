"""Domain types shared by the pure engine functions (plain dataclasses: fast, no I/O)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
DAY = 86400.0
HOUR = 3600.0


def parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    s = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(now: datetime, ts: datetime) -> float:
    return (now - ts).total_seconds() / DAY


def age_hours(now: datetime, ts: datetime) -> float:
    return (now - ts).total_seconds() / HOUR


@dataclass(slots=True)
class Event:
    event_id: str
    type: str
    ts: datetime
    actor: str = "prospect"
    rep_id: str | None = None
    source: str | None = None
    payload: dict = field(default_factory=dict)
    lead_id: str | None = None
    lead_ref: dict = field(default_factory=dict)
    derived: bool = False
    seq: int = 0
    cache: object = field(default=None, repr=False, compare=False)   # memoized pure derivations (signals)

    @property
    def sort_key(self) -> tuple:
        return (self.ts, self.event_id)

    def to_dict(self) -> dict:
        return {"event_id": self.event_id, "type": self.type, "ts": iso(self.ts), "actor": self.actor,
                "rep_id": self.rep_id, "source": self.source, "payload": self.payload, "lead_id": self.lead_id,
                "derived": self.derived, "seq": self.seq}


@dataclass(slots=True)
class Profile:
    lead_id: str | None = None
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    email_norm: str | None = None
    emails: list = field(default_factory=list)
    phone_e164: str | None = None
    phone_valid: bool | None = None
    title: str | None = None
    seniority: str = "unknown"
    company: str | None = None
    company_norm: str | None = None
    domain: str | None = None
    is_free_mail: bool = False
    country: str | None = None
    region: str | None = None
    ip: str | None = None
    source_primary: str | None = None
    sources: list = field(default_factory=list)
    capture_method: str | None = None
    created_at: datetime | None = None
    created_event_id: str | None = None
    # enrichment
    enriched: bool = False
    enriched_event_id: str | None = None
    account_id: str | None = None
    employees: int | None = None
    employee_band: str | None = None
    industry: str | None = None
    revenue_band: str | None = None
    hq_country: str | None = None
    tech_stack: list = field(default_factory=list)
    funding_stage: str | None = None
    # quality
    fake_score: float = 0.0
    fake_status: str = "clean"
    fake_signals: list = field(default_factory=list)
    quality_event_id: str | None = None
    quality_reviewed: bool = False
    disqualifier: str | None = None
    # deal hints
    budget: float | None = None
    seats: int | None = None
    merged_ids: list = field(default_factory=list)

    def copy(self) -> "Profile":
        p = Profile(**{f: getattr(self, f) for f in self.__dataclass_fields__})
        p.emails = list(self.emails)
        p.sources = list(self.sources)
        p.tech_stack = list(self.tech_stack)
        p.fake_signals = list(self.fake_signals)
        p.merged_ids = list(self.merged_ids)
        return p


@dataclass(slots=True)
class Factor:
    key: str                 # e.g. "intent.pricing_view"
    category: str            # fit | engagement | intent | penalty | clamp
    value: float             # points contributed to the score
    reason: str
    evidence: list = field(default_factory=list)
    label: str = ""
    raw: float = 0.0         # pre-saturation raw points (engagement / intent only)
    count: int = 0           # number of evidence events
    half_life: float | None = None

    def to_dict(self) -> dict:
        return {"key": self.key, "category": self.category, "value": round(self.value, 4), "reason": self.reason,
                "evidence": self.evidence, "label": self.label, "raw": round(self.raw, 4), "count": self.count,
                "half_life": self.half_life}

    @staticmethod
    def from_dict(d: dict) -> "Factor":
        return Factor(key=d["key"], category=d["category"], value=d["value"], reason=d.get("reason", ""),
                      evidence=list(d.get("evidence", [])), label=d.get("label", ""), raw=d.get("raw", 0.0),
                      count=d.get("count", 0), half_life=d.get("half_life"))


@dataclass(slots=True)
class ScoreResult:
    score: float
    grade: str
    fit: float
    engagement: float
    intent: float
    penalties: float
    factors: dict            # key -> Factor
    raw_engagement: float = 0.0
    raw_intent: float = 0.0
    intent_level: str = "none"
    active_signals: list = field(default_factory=list)

    def parts(self) -> dict:
        return {"fit": round(self.fit, 2), "engagement": round(self.engagement, 2), "intent": round(self.intent, 2),
                "penalties": round(self.penalties, 2)}


@dataclass(slots=True)
class Transition:
    ts: datetime
    from_stage: str
    to_stage: str
    rule_id: str
    evidence: list
    mode: str = "auto"
    reason: str = ""
    trigger_event_id: str | None = None

    def to_dict(self) -> dict:
        return {"ts": iso(self.ts), "from_stage": self.from_stage, "to_stage": self.to_stage, "rule_id": self.rule_id,
                "evidence_event_ids": self.evidence, "mode": self.mode, "reason": self.reason}


@dataclass(slots=True)
class LeadContext:
    """Inputs that live outside a lead's own event stream. Read from the store by the processor."""
    account_activity: list = field(default_factory=list)    # [(ts, other_lead_id)] prospect events at same account
    expired_actions: list = field(default_factory=list)     # [ts] NBA actions that expired undone
    rep_segment_win_rate: float | None = None
    team_win_rate: float = 0.25
    source_quality_index: float = 0.5
    owner_rep_id: str | None = None
