"""In-memory working set: event log, per-lead projections, indexes. SQLite (persistence.py) is the durable copy."""
from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .engine.assignment import smoothed_win_rate
from .engine.enrich import segment_for
from .engine.quotes import display_status
from .engine.types import Event, iso


@dataclass
class LeadRecord:
    lead_id: str
    source: str | None = None
    created_at: datetime | None = None
    status: str = "active"                # active | quarantined | merged | closed
    merged_into: str | None = None
    is_duplicate_capture: bool = False
    events: list = field(default_factory=list)
    fold: object = None                   # FoldState after last folded event
    ev: object = None                     # latest Evaluation
    last_factors: dict = field(default_factory=dict)
    last_stored_score: float = 0.0
    stage: str = "new"
    is_stalled: bool = False
    open_stall: dict | None = None
    owner: str | None = None
    assigned_at: datetime | None = None
    auto_reassign_count: int = 0
    first_touch_deadline: datetime | None = None
    priority: float = 0.0
    priority_drivers: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    expired_action_ts: list = field(default_factory=list)
    transitions: list = field(default_factory=list)
    score_history: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    stall_flags: list = field(default_factory=list)
    quality: dict | None = None
    outcome_counted: bool = False
    last_eval_at: datetime | None = None

    @property
    def profile(self):
        return self.fold.profile if self.fold else None

    def open_action(self) -> dict | None:
        for a in reversed(self.actions):
            if a["status"] == "open":
                return a
        return None


class Store:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clock = None                  # set by the runtime; quote expiry is judged against it
        self.historical: list[dict] = []
        self.raw_log: list[dict] = []
        self.reset_projections()

    def reset_all(self) -> None:
        self.historical = []
        self.raw_log = []
        self.reset_projections()

    def reset_projections(self) -> None:
        cfg = self.cfg
        self.events: dict[str, Event] = {}
        self.log: list[Event] = []
        self.ingested_at: dict[str, datetime] = {}
        self.leads: dict[str, LeadRecord] = {}
        self.block_index: dict[tuple, set] = defaultdict(set)
        self.account_index: dict[str, set] = defaultdict(set)
        self.owner_index: dict[str, set] = defaultdict(set)
        self.ip_index: dict[str, deque] = defaultdict(deque)
        self.reps = {r["rep_id"]: dict(r) for r in cfg.data.reps}
        self.rep_stats = {rid: {"wins": defaultdict(int), "closed": defaultdict(int), "last_assigned_at": None,
                                "neglect_count": 0, "assigned": 0, "reassigned_away": 0, "revenue": 0.0}
                          for rid in self.reps}
        self.merges: list[dict] = []
        self.review: dict[str, dict] = {}
        self.feed: deque = deque(maxlen=400)
        self.source_stats: dict[str, dict] = {}
        self.source_flags: dict[str, list] = {}
        self.source_daily: list[dict] = []
        self.counters: dict[str, int] = defaultdict(int)
        self.p95_ev = 1.0
        self.team_win_rate = 0.25
        self.latencies: deque = deque(maxlen=5000)
        self.last_tick_at: datetime | None = None
        self.last_snapshot_day: str | None = None
        self.unresolved: list[str] = []
        self.opps: dict[str, object] = {}                      # opp_id -> engine.opportunity.Opportunity
        self.opp_evals: dict[str, dict] = {}                   # opp_id -> evaluation at the last refresh
        self.account_opps: dict[str, list] = defaultdict(list)  # account key -> opp ids, in opening order
        self.lead_account: dict[str, str] = {}                 # lead_id -> account key used at the last refresh
        self.quote_rows: dict[str, dict] = {}                  # quote_id -> projection row at the last refresh
        self.quote_tokens: dict[str, tuple] = {}               # buyer link token -> (opp_id, quote_id)
        self.load_history(self.historical)

    # ---------------------------------------------------------------- ids / history
    def next_id(self, kind: str) -> int:
        self.counters[kind] += 1
        return self.counters[kind]

    def new_lead_id(self) -> str:
        return f"L-{1000 + self.next_id('lead')}"

    def load_history(self, deals: list[dict]) -> None:
        for d in deals:
            st = self.rep_stats.get(d["rep_id"])
            if st is None:
                continue
            st["closed"][d["segment"]] += 1
            if d["won"]:
                st["wins"][d["segment"]] += 1
                st["revenue"] += d.get("amount") or 0
        self._recompute_team_rate()

    def record_outcome(self, rep_id: str | None, segment: str | None, won: bool, amount: float = 0.0) -> None:
        st = self.rep_stats.get(rep_id or "")
        if st is None:
            return
        seg = segment or "smb"
        st["closed"][seg] += 1
        if won:
            st["wins"][seg] += 1
            st["revenue"] += amount
        self._recompute_team_rate()

    def _recompute_team_rate(self) -> None:
        wins = sum(sum(s["wins"].values()) for s in self.rep_stats.values())
        closed = sum(sum(s["closed"].values()) for s in self.rep_stats.values())
        self.team_win_rate = wins / closed if closed else 0.25

    def rep_segment_win_rate(self, rep_id: str | None, segment: str | None) -> float | None:
        st = self.rep_stats.get(rep_id or "")
        if st is None:
            return None
        seg = segment or "smb"
        return smoothed_win_rate(st["wins"][seg], st["closed"][seg], self.team_win_rate, self.cfg)

    # ---------------------------------------------------------------- indexes
    def resolve_lead_id(self, lead_id: str | None) -> str | None:
        seen = set()
        while lead_id and lead_id in self.leads and self.leads[lead_id].status == "merged":
            if lead_id in seen:
                break
            seen.add(lead_id)
            lead_id = self.leads[lead_id].merged_into
        return lead_id if lead_id in self.leads else None

    def ip_hit(self, ip: str | None, ts: datetime) -> int:
        if not ip:
            return 0
        dq = self.ip_index[ip]
        dq.append(ts)
        cutoff = ts - timedelta(hours=1)
        return sum(1 for t in dq if cutoff < t <= ts)

    def is_open(self, lead: LeadRecord) -> bool:
        return lead.status in ("active",) and lead.stage not in self.cfg.derived.terminal

    def rep_load(self, rep_id: str) -> int:
        w = self.cfg.assignment.load_weight
        total = 0
        for lid in self.owner_index.get(rep_id, ()):
            lead = self.leads[lid]
            if self.is_open(lead) and lead.stage != "nurture":
                total += w[lead.ev.score.grade if lead.ev else "D"]
        return total

    def set_owner_index(self, lead: LeadRecord, new_owner: str | None) -> None:
        if lead.owner:
            self.owner_index[lead.owner].discard(lead.lead_id)
        if new_owner:
            self.owner_index[new_owner].add(lead.lead_id)

    # ---------------------------------------------------------------- views
    def rep_name(self, rep_id: str | None) -> str | None:
        if rep_id == self.cfg.assignment.reassignment.manager_queue_id:
            return "Manager queue"
        r = self.reps.get(rep_id or "")
        return r["name"] if r else None

    def lead_view(self, lead: LeadRecord, detail: bool = False) -> dict:
        ev = lead.ev
        p = lead.profile
        if ev is None or p is None:
            return {"lead_id": lead.lead_id, "status": lead.status, "merged_into": lead.merged_into,
                    "source": lead.source, "created_at": iso(lead.created_at)}
        act = lead.open_action()
        m = ev.metrics
        view = {
            "lead_id": lead.lead_id, "name": p.name, "company": p.company, "title": p.title, "email": p.email,
            "phone": p.phone_e164, "country": p.country, "region": p.region, "industry": p.industry,
            "employees": p.employees, "segment": ev.segment, "source": p.source_primary or lead.source,
            "sources": p.sources, "status": lead.status, "merged_into": lead.merged_into,
            "owner_rep_id": lead.owner, "owner_name": self.rep_name(lead.owner), "stage": ev.stage,
            "stage_entered_at": iso(ev.stage_entered_at), "days_in_stage": round(ev.days_in_stage, 2),
            "is_stalled": ev.stall["is_stalled"], "stall": ev.stall, "score": round(ev.score.score, 2),
            "grade": ev.score.grade, "intent_level": ev.score.intent_level, "active_signals": ev.score.active_signals,
            "parts": ev.score.parts(), "fake_score": p.fake_score, "fake_status": p.fake_status,
            "predicted_acv": ev.acv["acv"], "acv_p10": ev.acv["p10"], "acv_p90": ev.acv["p90"],
            "close_prob": round(ev.close["p"], 4), "expected_value": round(ev.expected_value, 2),
            "priority": lead.priority, "priority_drivers": lead.priority_drivers[:2],
            "created_at": iso(p.created_at or lead.created_at), "last_inbound_at": iso(m["last_inbound_at"]),
            "last_outbound_at": iso(m["last_outbound_at"]), "first_response_at": iso(m["first_response_at"]),
            "first_response_minutes": m["first_response_minutes"],
            "primary_action": _action_view(act), "sla_deadline": iso(lead.first_touch_deadline),
            "auto_reassign_count": lead.auto_reassign_count,
            "sparkline": [round(r["new_score"], 1) for r in lead.score_history[-24:]],
        }
        if detail:
            view.update({
                "alternates": act.get("alternates", []) if act else [],
                "factors": {k: f.to_dict() for k, f in ev.score.factors.items()},
                "acv_factors": ev.acv["factors"], "close_factors": ev.close["factors"],
                "metrics": {k: (iso(v) if isinstance(v, datetime) else v) for k, v in m.items()},
                "quality": lead.quality, "merged_ids": p.merged_ids, "emails": p.emails,
                "seniority": p.seniority, "revenue_band": p.revenue_band, "tech_stack": p.tech_stack,
                "funding_stage": p.funding_stage, "account_id": p.account_id, "disqualifier": p.disqualifier,
                "budget": p.budget, "seats": p.seats, "fake_signals": p.fake_signals,
                "opportunities": [self.opp_view(o) for o in self.opps_for_lead(lead.lead_id)],
            })
        return view

    # ---------------------------------------------------------------- accounts and deals
    @staticmethod
    def account_key(lead: LeadRecord) -> str:
        """A company is keyed by its web domain; a lead without one (free mail) is an account of its own."""
        p = lead.profile
        return p.account_id if p is not None and p.account_id else f"lead:{lead.lead_id}"

    def account_contacts(self, key: str) -> list[LeadRecord]:
        ids = self.account_index.get(key, ()) if not key.startswith("lead:") else (key[5:],)
        out = [self.leads[i] for i in sorted(ids) if i in self.leads]
        return [l for l in out if l.status != "merged" and l.fold is not None]

    def opps_for_lead(self, lead_id: str) -> list:
        key = self.lead_account.get(lead_id)
        return [o for oid in self.account_opps.get(key, ()) if (o := self.opps.get(oid)) and lead_id in o.contact_ids]

    def opp_view(self, o, detail: bool = False) -> dict:
        ev = self.opp_evals.get(o.opp_id) or {}
        primary = self.leads.get(o.primary_lead_id)
        owner = primary.owner if primary else None
        p = primary.profile if primary else None
        view = {
            "opp_id": o.opp_id, "name": o.name, "kind": o.kind, "status": o.status, "stage": o.stage,
            "account_id": None if o.account_key.startswith("lead:") else o.account_key,
            "company": p.company if p else None, "primary_lead_id": o.primary_lead_id,
            "contacts": len(o.contact_ids), "owner_rep_id": owner, "owner_name": self.rep_name(owner),
            "opened_at": iso(o.opened_at), "closed_at": iso(o.closed_at), "stage_entered_at": iso(o.stage_entered_at),
            "days_in_stage": round(ev.get("days_in_stage", 0.0), 1), "amount": o.amount,
            "acv": ev["acv"]["acv"] if ev else None, "close_prob": round(ev["close"]["p"], 4) if ev else None,
            "expected_value": round(ev.get("expected_value", 0.0), 2),
            "is_stalled": bool(ev and ev["stall"]["is_stalled"]), "stall": ev.get("stall"),
            "close_date": o.close_date, "lost_reason": o.lost_reason, "last_activity_at": iso(o.last_activity_at),
            "committee_covered": ev["committee"]["covered"] if ev else [],
            "quote": self._latest_quote(o),
        }
        if detail:
            people = []
            for lid in o.contact_ids:
                lead = self.leads.get(lid)
                if lead is None or lead.ev is None:
                    continue
                lp = lead.profile
                people.append({"lead_id": lid, "name": lp.name, "title": lp.title, "seniority": lp.seniority,
                               "email": lp.email, "score": round(lead.ev.score.score, 1), "grade": lead.ev.score.grade,
                               "stage": lead.ev.stage, "owner_rep_id": lead.owner, "primary": lid == o.primary_lead_id})
            view.update({
                "contacts_detail": people, "committee": ev.get("committee"),
                "acv_factors": ev["acv"]["factors"] if ev else [], "close_factors": ev["close"]["factors"] if ev else [],
                "transitions": [{**t, "ts": iso(t["ts"])} for t in o.transitions],
                "open_rule": o.open_rule, "opened_event_id": o.opened_event_id, "events": len(o.event_ids),
                "created_by": o.created_by,
                "quotes": [self.quote_view(o, q) for q in reversed(list(o.quotes.values()))],
            })
        return view

    # ---------------------------------------------------------------- quotes
    def today(self) -> str | None:
        return self.clock.now().date().isoformat() if self.clock is not None else None

    def _latest_quote(self, o) -> dict | None:
        """The newest quote that still counts (for deal cards): not voided or superseded."""
        q = next((q for q in reversed(list(o.quotes.values())) if q.status not in ("void", "superseded")), None)
        return {"quote_id": q.quote_id, "status": display_status(q, self.today()), "total": q.totals.get("total")} if q else None

    def quote_view(self, o, q, buyer: bool = False) -> dict:
        """One quote. buyer=True is what the buyer's link shows: no internal fields."""
        lead = self.leads.get(q.lead_id)
        lp = lead.profile if lead is not None else None
        view = {
            "quote_id": q.quote_id, "title": q.title, "status": display_status(q, self.today()),
            "currency": self.cfg.quotes.currency, "valid_until": q.valid_until, "lines": q.lines,
            "discount_pct": q.discount_pct, "totals": q.totals, "notes": q.notes, "terms": q.terms,
            "created_at": iso(q.created_at), "sent_at": iso(q.sent_at), "accepted_at": iso(q.accepted_at),
            "declined_at": iso(q.declined_at), "decline_reason": q.decline_reason,
            "accepted_by": q.accepted_by, "deal_name": o.name, "company": lp.company if lp else None,
            "recipient": {"lead_id": q.lead_id, "name": lp.name if lp else None, "title": lp.title if lp else None,
                          "email": lp.email if lp else None},
        }
        if buyer:
            view["recipient"].pop("lead_id")
            return view
        view.update({
            "opp_id": o.opp_id, "rev": q.rev, "base_status": q.status, "created_by": q.created_by,
            "updated_at": iso(q.updated_at), "sent_by": q.sent_by, "viewed_at": iso(q.viewed_at),
            "last_viewed_at": iso(q.last_viewed_at), "views": q.views, "needs_approval": q.needs_approval,
            "approved": q.approved, "approved_by": q.approved_by if q.approved else None,
            "approved_at": iso(q.approved_at) if q.approved else None, "ready": q.ready,
            "max_discount_pct": self.cfg.quotes.approval.max_discount_pct,
            "voided_at": iso(q.voided_at), "void_reason": q.void_reason, "supersedes": q.supersedes,
            "superseded_by": q.superseded_by, "link": f"/q/{q.token}" if q.token else None,
        })
        return view

    def percentile(self, values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        vs = sorted(values)
        k = (len(vs) - 1) * pct / 100
        lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
        return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)

    def latency_stats(self) -> dict:
        lat = list(self.latencies)
        if not lat:
            return {"count": 0}
        return {"count": len(lat), "p50_ms": round(statistics.median(lat), 2),
                "p95_ms": round(self.percentile(lat, 95), 2), "max_ms": round(max(lat), 2)}

    def segment_of(self, lead: LeadRecord) -> str | None:
        return segment_for(lead.profile.employees if lead.profile else None, self.cfg)


def _action_view(a: dict | None) -> dict | None:
    if not a:
        return None
    return {"id": a["id"], "rule_id": a["rule_id"], "action": a["action"], "channel": a["channel"],
            "due_at": iso(a["due_at"]), "urgency": a["urgency"], "reason": a["reason"], "template": a["template"],
            "completion": a.get("completion"), "rep_id": a.get("rep_id"), "created_at": iso(a["ts"])}
