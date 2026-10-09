"""Test helpers: deterministic event builders."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.engine.enrich import MockEnrichmentProvider, enrich
from app.engine.normalize import normalize_capture
from app.engine.pipeline import run_fold
from app.engine.quality import assess
from app.engine.types import UTC, Event, LeadContext

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)

REP_TYPES = {"email_sent", "call_logged", "meeting_scheduled", "meeting_held", "meeting_no_show", "proposal_sent",
             "contract_sent", "deal_won", "deal_lost", "task_created", "task_completed", "stage_override",
             "lead_disqualified", "bant_qualified"}
SYSTEM_TYPES = {"lead_enriched", "quality_assessed", "quality_cleared", "lead_merged", "time_tick", "email_bounced"}


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


class Builder:
    def __init__(self, lead_id: str = "L-1001", prefix: str = "e"):
        self.lead_id = lead_id
        self.prefix = prefix
        self.n = 0
        self.events: list[Event] = []

    def ev(self, type_: str, hours: float = 0.0, actor: str | None = None, rep_id: str | None = None,
           source: str = "website", derived: bool = False, **payload) -> Event:
        self.n += 1
        if actor is None:
            actor = "rep" if type_ in REP_TYPES else "system" if type_ in SYSTEM_TYPES else "prospect"
        if actor == "rep" and rep_id is None:
            rep_id = "R-ANANYA"
        e = Event(event_id=f"{self.prefix}{self.n:05d}", type=type_, ts=at(hours), actor=actor, rep_id=rep_id,
                  source=source, payload=payload, lead_id=self.lead_id, derived=derived)
        self.events.append(e)
        return e

    def page(self, category: str, hours: float) -> Event:
        return self.ev("page_view", hours, url=f"/{category}", page_category=category)

    def reply(self, body: str, hours: float) -> Event:
        return self.ev("email_replied", hours, body=body)

    def capture(self, cfg, hours: float = 0.0, name: str = "Priya Nair", email: str = "priya.nair@finnova.sg",
                company: str = "FinNova Payments", title: str = "Head of Operations", country: str = "SG",
                capture_method: str = "form_submit", source: str = "website", phone: str | None = None,
                ip: str = "112.10.0.1", **extra) -> list[Event]:
        extra.setdefault("form_fill_seconds", 25)
        payload = dict(name=name, email=email, company=company, title=title, country=country,
                       capture_method=capture_method, phone=phone, ip=ip, **extra)
        created = self.ev("lead_created", hours, source=source, **payload)
        ident = normalize_capture(payload, cfg)
        prov = MockEnrichmentProvider(cfg)
        q = assess(ident, payload, {"ip_submissions_last_hour": 1, "mx_valid": prov.mx_valid(ident["email_domain"]),
                                    "ip_country": prov.ip_country(ip),
                                    "disposable": prov.is_disposable(ident["email_domain"])}, cfg)
        out = [created]
        self.n += 1
        qa = Event(event_id=f"{created.event_id}.1q", type="quality_assessed", ts=created.ts, actor="system",
                   payload=q, lead_id=self.lead_id, derived=True)
        self.events.append(qa)
        out.append(qa)
        enr = enrich(ident, prov, cfg)
        if enr:
            ee = Event(event_id=f"{created.event_id}.2e", type="lead_enriched", ts=created.ts, actor="system",
                       payload=enr, lead_id=self.lead_id, derived=True)
            self.events.append(ee)
            out.append(ee)
        return out

    def sorted(self) -> list[Event]:
        return sorted(self.events, key=lambda e: e.sort_key)


def fold(cfg, events: list[Event], ctx: LeadContext | None = None):
    evs = sorted(events, key=lambda e: e.sort_key)
    return run_fold(evs, ctx or LeadContext(), cfg, lead_id="L-1001")


def evaluate_at(cfg, events: list[Event], hours: float, ctx: LeadContext | None = None):
    from app.engine.evaluate import evaluate
    now = at(hours)
    evs = sorted([e for e in events if e.ts <= now], key=lambda e: e.sort_key)
    ctx = ctx or LeadContext()
    st, _ = run_fold(evs, ctx, cfg, lead_id="L-1001")
    return evaluate(st, evs, now, ctx, cfg)
