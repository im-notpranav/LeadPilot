"""Scripted, deterministic demo scenarios (launchable from the UI).

History events are injected immediately with ingested_at = ts (an import of past activity); live events are
scheduled relative to the current simulated time and play out with the clock.
"""
from __future__ import annotations

import random
from datetime import timedelta

from ..engine.types import iso
from .personas import bot_identity

SCENARIOS = {
    "reviver": {
        "title": "Reviver",
        "description": "Priya Nair, Head of Ops at a 300-person fintech, has gone quiet (score ~28, grade D, in nurture). "
                       "She visits pricing 3x within 48h, then requests a demo.",
        "expected": ["Score climbs to ~75 with step-by-step explanations", "Intent becomes hot",
                     "Stage: nurture -> engaged (P10) -> qualified (P3)", "Owned by the fintech / APAC rep",
                     "Next best action: Call now and book a demo (15 min)"],
        "duration_hours": 15,
    },
    "ghoster": {
        "title": "Ghoster",
        "description": "Tom Becker's deal is at proposal, then the prospect stops replying to follow-ups.",
        "expected": ["Day 7+: stalled (S1 inactivity + S4 ghosting)", "Close probability drops",
                     "Next best action: multi-thread", "Score decays with explained ticks"],
        "duration_hours": 24 * 8,
    },
    "duplicate": {
        "title": "Duplicate",
        "description": "Rahul arrives via a webinar (rahul.k@acme.io), then again via Google Ads as Rahul Kumar "
                       "(+91..., rahul.k+ads@acme.io).",
        "expected": ["Auto-merge at confidence 1.00 (same normalized email)",
                     "Survivor re-scored from the combined history with a 'merge' contribution"],
        "duration_hours": 1,
    },
    "bot_burst": {
        "title": "Bot burst",
        "description": "20 junk leads from list_vendor_x in 10 minutes, all from one IP.",
        "expected": ["All quarantined as fake (disqualified, never assigned)",
                     "list_vendor_x flagged on the next hourly source-quality refresh"],
        "duration_hours": 1.5,
    },
    "neglected": {
        "title": "Neglected hot lead",
        "description": "A grade-A lead (VP at a 1,500-person healthcare IT company who just requested a demo) is "
                       "assigned to a neglectful rep. An hour passes with no touch.",
        "expected": ["R1 first-touch SLA (1h for grade A) breached", "Lead reassigned with the reason recorded",
                     "Previous rep's neglect count increments"],
        "duration_hours": 1.5,
    },
}


class ScenarioCtx:
    def __init__(self, rt, name: str, run: int):
        self.rt = rt
        self.name = name
        self.run = run
        self.n = 0
        self.now = rt.clock.now()

    def eid(self) -> str:
        self.n += 1
        return f"scn_{self.name}{self.run}_{self.n:03d}"

    def tag(self, local: str) -> str:
        return local if self.run == 1 else f"{local}{self.run}"

    def _event(self, type_: str, ts, lead_id=None, actor=None, rep=None, source=None, **payload) -> dict:
        if actor is None:
            actor = "rep" if rep else "prospect"
        return {"event_id": self.eid(), "type": type_, "ts": iso(ts), "actor": actor, "rep_id": rep, "source": source,
                "lead_ref": {"lead_id": lead_id} if lead_id else {}, "payload": payload}

    def history(self, type_: str, hours_ago: float, lead_id=None, **kw) -> dict:
        ts = self.now - timedelta(hours=hours_ago)
        ev = self._event(type_, ts, lead_id, **kw)
        ev["ingested_at"] = ev["ts"]
        ev["import"] = True
        return self.rt.emit(ev)

    def now_event(self, type_: str, lead_id=None, **kw) -> dict:
        return self.rt.emit(self._event(type_, self.now, lead_id, **kw))

    def future(self, type_: str, hours_ahead: float, lead_id=None, **kw) -> None:
        ts = self.now + timedelta(hours=hours_ahead)
        self.rt.schedule_event(ts, self._event(type_, ts, lead_id, **kw))

    def owner(self, lead_id: str) -> str | None:
        return self.rt.store.leads[lead_id].owner

    def refresh(self, lead_id: str) -> dict:
        return self.rt.emit(self._event("lead_refresh", self.now, lead_id, actor="system"))


def launch(rt, name: str) -> dict:
    if name not in SCENARIOS:
        raise KeyError(name)
    rt.scenario_runs[name] = rt.scenario_runs.get(name, 0) + 1
    ctx = ScenarioCtx(rt, name, rt.scenario_runs[name])
    rt.sim.suspended = True
    try:
        info = globals()[f"_{name}"](ctx)
    finally:
        rt.sim.suspended = False
    meta = SCENARIOS[name]
    return {"scenario": name, "title": meta["title"], "expected": meta["expected"], "started_at": iso(ctx.now),
            "ends_at": iso(ctx.now + timedelta(hours=meta["duration_hours"])), **info}


def _reviver(s: ScenarioCtx) -> dict:
    lead = s.history("lead_created", 35 * 24, source="website", name="Priya Nair",
                     email=f"{s.tag('priya.nair')}@finnova.sg", company="FinNova Payments Pte Ltd",
                     title="Head of Operations", country="SG", phone="+65 8123 4567", ip="112.40.2.9",
                     capture_method="form_submit", form_fill_seconds=48)["lead_id"]
    s.history("page_view", 35 * 24 - 0.2, lead, url="/blog/payments-ops", page_category="blog")
    s.history("content_download", 35 * 24 - 0.5, lead, asset="ops-playbook.pdf")
    s.history("email_sent", 34 * 24, lead, rep=s.owner(lead), template="first_touch")
    s.history("email_opened", 33.8 * 24, lead)
    s.refresh(lead)
    s.future("email_clicked", 0.2, lead, url="/pricing")
    s.future("page_view", 0.25, lead, url="/pricing", page_category="pricing")
    s.future("page_view", 2, lead, url="/customers/fintech-roi", page_category="case_study")
    s.future("page_view", 6, lead, url="/pricing", page_category="pricing")
    s.future("page_view", 12, lead, url="/pricing", page_category="pricing")
    s.future("demo_request", 14, lead, form="book-a-demo")
    return {"lead_id": lead}


def _ghoster(s: ScenarioCtx) -> dict:
    lead = s.history("lead_created", 20 * 24, source="referral", name="Tom Becker",
                     email=f"{s.tag('tom.becker')}@northwindlogistics.com", company="Northwind Logistics",
                     title="VP Supply Chain", country="US", ip="23.9.14.2", capture_method="referral",
                     form_fill_seconds=60)["lead_id"]
    rep = s.owner(lead)
    s.history("email_sent", 20 * 24 - 2, lead, rep=rep, template="first_touch")
    s.history("email_replied", 19 * 24, lead,
              body="Interested. What does the timeline look like, and can we book a demo next week?")
    s.history("meeting_scheduled", 18 * 24, lead, rep=rep, meeting_type="discovery",
              scheduled_for=iso(s.now - timedelta(days=15)))
    s.history("meeting_held", 15 * 24, lead, rep=rep, meeting_type="discovery")
    s.history("meeting_held", 9 * 24, lead, rep=rep, meeting_type="demo")
    s.history("email_replied", 8 * 24, lead, body="Good timing. Can you walk us through pricing and next steps?")
    s.history("proposal_sent", 24, lead, rep=rep, amount=78000)
    s.history("proposal_viewed", 20, lead)
    s.refresh(lead)
    for d in (2, 4, 6):
        s.future("email_sent", d * 24, lead, rep=rep, template="follow_up")
    return {"lead_id": lead}


def _duplicate(s: ScenarioCtx) -> dict:
    lead = s.history("lead_created", 72, source="webinar", name="Rahul K", email=f"{s.tag('rahul.k')}@acme.io",
                     company="Acme Inc", title="Engineering Manager", country="IN", ip="103.21.4.8",
                     capture_method="form_submit", webinar="Scaling revenue ops", form_fill_seconds=35)["lead_id"]
    s.history("webinar_attended", 71, lead, webinar="Scaling revenue ops")
    s.history("email_sent", 69, lead, rep=s.owner(lead), template="first_touch")
    s.history("content_download", 48, lead, asset="roi-calculator.xlsx")
    s.refresh(lead)
    s.future("lead_created", 0.1, source="google_ads", name="Rahul Kumar",
             email=f"{s.tag('rahul.k')}+ads@acme.io", phone="+91 98201 23456", country="IN", company="Acme",
             ip="103.21.4.8", capture_method="ad_lead", form_fill_seconds=22)
    return {"lead_id": lead}


def _bot_burst(s: ScenarioCtx) -> dict:
    rng = random.Random(f"bots-{s.run}")
    ip = f"185.220.{100 + s.run}.7"
    for i in range(20):
        payload = bot_identity(rng, s.rt.cfg, ip)
        s.future("lead_created", i * 0.5 / 60, source="list_vendor_x", **payload)
    return {"ip": ip, "count": 20}


def _neglected(s: ScenarioCtx) -> dict:
    lead = s.history("lead_created", 48, source="website", name="Dana Wells",
                     email=f"{s.tag('dana.wells')}@helixhealth.com", company="Helix Health Systems",
                     title="VP of Operations", country="US", ip="23.44.10.3", capture_method="form_submit",
                     form_fill_seconds=51)["lead_id"]
    s.history("content_download", 47, lead, asset="security-whitepaper.pdf")
    s.history("webinar_attended", 24, lead, webinar="Product deep dive")
    for h in (20, 10, 3):
        s.history("page_view", h, lead, url="/pricing", page_category="pricing")
    s.history("page_view", 2, lead, url="/enterprise", page_category="enterprise_plan")
    s.history("page_view", 1.5, lead, url="/customers/health-roi", page_category="case_study")
    s.history("contact_sales", 1, lead, form="contact-sales")
    s.history("demo_request", 0.5, lead, form="book-a-demo")
    s.refresh(lead)
    s.now_event("manual_assign", lead, actor="manager", rep_id="R-VICTOR",
                reason="Assigned to Victor Hale by sales manager")
    return {"lead_id": lead, "assigned_to": "R-VICTOR"}
