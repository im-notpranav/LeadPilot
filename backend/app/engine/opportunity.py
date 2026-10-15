"""Accounts and deals (opportunities), pure.

An account is a company, keyed by its web domain; leads without a company domain are their own account. A deal
belongs to an account and can involve several of its contacts. Deals are a deterministic fold over the account's
events in timestamp order, like the lead pipeline, so a replay or out-of-order arrival yields the same deals.

  O0  a rep creates a deal (opportunity_created)
  O1  the first buying signal from a contact opens a deal when the account has none open: new business, or
      expansion once the account has won before
  O4  meeting held · O5 proposal sent · O6 contract sent, or a negotiating reply after a proposal
  O7  won · O8 lost · OM moved by hand (opportunity_updated with a stage)

An event carrying payload.opportunity_id goes to that deal; any other event goes to the account's most recently
opened deal that is still open. Quote events (engine/quotes.py) always name their deal; a deal's quotes are folded
along with it.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime

from .intent import has_negotiation_terms, reply_class
from .metrics import is_inbound
from .prediction import close_probability, predict_acv
from .quotes import QUOTE_TYPES, apply_quote_event
from .types import Event, LeadContext, Profile, ScoreResult, age_days

FORWARD = ("qualified", "meeting", "proposal", "negotiation", "won")
EXPLICIT_TYPES = ("opportunity_created", "opportunity_updated")


@dataclass
class Opportunity:
    opp_id: str
    account_key: str
    kind: str                       # new_business | expansion | renewal
    name: str
    opened_at: datetime
    opened_event_id: str
    open_rule: str
    primary_lead_id: str
    contact_ids: list = field(default_factory=list)
    stage: str = "qualified"
    stage_entered_at: datetime | None = None
    transitions: list = field(default_factory=list)
    event_ids: list = field(default_factory=list)
    amount: float | None = None
    close_date: str | None = None
    closed_at: datetime | None = None
    lost_reason: str | None = None
    last_activity_at: datetime | None = None
    last_inbound_at: datetime | None = None
    proposal_sent_at: datetime | None = None
    created_by: str | None = None
    quotes: dict = field(default_factory=dict)      # quote_id -> engine.quotes.Quote, in creation order

    @property
    def status(self) -> str:
        return self.stage if self.stage in ("won", "lost") else "open"


def opp_id_for(account_key: str, event_id: str) -> str:
    return "O-" + hashlib.sha1(f"{account_key}|{event_id}".encode()).hexdigest()[:10]


def deal_name(company: str | None, kind: str) -> str:
    label = {"new_business": "New business", "expansion": "Expansion", "renewal": "Renewal"}.get(kind, kind)
    return f"{company} · {label}" if company else label


def _move(o: Opportunity, to: str, rule: str, e: Event, cfg, reason: str | None = None, mode: str = "auto") -> None:
    if to == o.stage:
        return
    o.transitions.append({"ts": e.ts, "from": o.stage, "to": to, "rule_id": rule, "evidence": [e.event_id],
                          "reason": reason or cfg.pipeline.opportunities.rule_labels.get(rule, rule), "mode": mode})
    o.stage, o.stage_entered_at = to, e.ts
    if to in ("won", "lost"):
        o.closed_at = e.ts
    else:
        o.closed_at, o.lost_reason = None, None


def _advance(o: Opportunity, to: str, rule: str, e: Event, cfg) -> None:
    """Forward-only automatic move; closed deals only change by hand."""
    if o.status != "open" or FORWARD.index(to) <= FORWARD.index(o.stage):
        return
    _move(o, to, rule, e, cfg)


def _open(account_key: str, oid: str, e: Event, rule: str, kind: str, name: str, cfg) -> Opportunity:
    o = Opportunity(opp_id=oid, account_key=account_key, kind=kind, name=name, opened_at=e.ts,
                    opened_event_id=e.event_id, open_rule=rule, primary_lead_id=e.lead_id, stage="qualified",
                    stage_entered_at=e.ts)
    o.transitions.append({"ts": e.ts, "from": None, "to": "qualified", "rule_id": rule, "evidence": [e.event_id],
                          "reason": cfg.pipeline.opportunities.rule_labels.get(rule, rule),
                          "mode": "manual" if rule == "O0" else "auto"})
    return o


def _amount(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and math.isfinite(v) else None


def _touch(o: Opportunity, e: Event, cfg) -> None:
    if e.lead_id and e.lead_id not in o.contact_ids:
        o.contact_ids.append(e.lead_id)
    o.event_ids.append(e.event_id)
    o.last_activity_at = e.ts
    if is_inbound(e, cfg):
        o.last_inbound_at = e.ts


def _route(o: Opportunity, e: Event, cfg) -> None:
    pl = e.payload or {}
    t = e.type
    _touch(o, e, cfg)
    if t in ("proposal_sent", "contract_sent", "deal_won", *EXPLICIT_TYPES) and _amount(pl.get("amount")):
        o.amount = _amount(pl.get("amount"))
    if t in EXPLICIT_TYPES:
        if pl.get("close_date"):
            o.close_date = str(pl["close_date"])[:10]
        if pl.get("name"):
            o.name = str(pl["name"])[:120]
    if t == "opportunity_updated" and pl.get("stage") in cfg.pipeline.opportunities.stages:
        _move(o, pl["stage"], "OM", e, cfg, reason=pl.get("reason") or "Moved by hand", mode="manual")
        if pl["stage"] == "lost":
            o.lost_reason = pl.get("lost_reason") or pl.get("reason")
        return
    if t == "meeting_held" and pl.get("meeting_type", "discovery") in cfg.pipeline.rules.P4_meeting_types:
        _advance(o, "meeting", "O4", e, cfg)
    elif t == "proposal_sent":
        o.proposal_sent_at = e.ts
        _advance(o, "proposal", "O5", e, cfg)
    elif t == "contract_sent":
        _advance(o, "negotiation", "O6", e, cfg)
    elif t == "email_replied" and o.proposal_sent_at is not None and reply_class(pl, cfg) == "positive_intent" \
            and has_negotiation_terms(pl.get("body"), cfg):
        _advance(o, "negotiation", "O6", e, cfg)
    elif t == "deal_won" and o.status == "open":
        _move(o, "won", "O7", e, cfg)
    elif t == "deal_lost" and o.status == "open":
        _move(o, "lost", "O8", e, cfg, reason=f"Deal lost: {pl.get('lost_reason', 'unspecified')}")
        o.lost_reason = pl.get("lost_reason")


def fold_opportunities(account_key: str, events: list[Event], eligible: set, company: str | None, cfg) -> list:
    """All deals of one account. `events` are the account contacts' events, sorted by (ts, event_id), each with its
    lead_id. Only `eligible` contacts (not fake, not quarantined) can open a deal on a buying signal."""
    oc = cfg.pipeline.opportunities
    opps: list[Opportunity] = []
    by_id: dict[str, Opportunity] = {}
    for e in events:
        if e.derived or not e.lead_id:
            continue
        pl = e.payload or {}
        won_before = any(o.stage == "won" for o in opps)
        if e.type == "opportunity_created":
            oid = str(pl.get("opportunity_id") or opp_id_for(account_key, e.event_id))
            if oid in by_id:
                continue
            kind = pl.get("kind") or ("expansion" if won_before else "new_business")
            o = _open(account_key, oid, e, "O0", kind, str(pl.get("name") or deal_name(company, kind))[:120], cfg)
            o.created_by = pl.get("by")
            opps.append(o)
            by_id[oid] = o
            _route(o, e, cfg)
            continue
        target = by_id.get(str(pl["opportunity_id"])) if pl.get("opportunity_id") else None
        if pl.get("quote_id") and target is not None:
            apply_quote_event(target.quotes, target.opp_id, e, cfg)
        if e.type in QUOTE_TYPES:                      # quote bookkeeping: activity on the deal, nothing more
            if target is not None and target.status == "open":
                _touch(target, e, cfg)
            continue
        if target is None:
            target = next((o for o in reversed(opps) if o.status == "open"), None)
        elif target.status != "open" and e.type != "opportunity_updated":
            continue                                   # a closed deal only changes by hand
        if target is None:
            if e.type not in oc.open_on or e.lead_id not in eligible:
                continue
            kind = "expansion" if won_before else "new_business"
            target = _open(account_key, opp_id_for(account_key, e.event_id), e, "O1", kind,
                           deal_name(company, kind), cfg)
            opps.append(target)
            by_id[target.opp_id] = target
        _route(target, e, cfg)
    return opps


# ------------------------------------------------------------------------------------------------ evaluation at now
def committee_role(seniority: str | None, cfg) -> str:
    for role, levels in cfg.pipeline.opportunities.committee_roles.items():
        if (seniority or "unknown") in levels:
            return role
    return "practitioner"


def committee(contacts: list[dict], cfg) -> dict:
    """contacts: [{lead_id, name, title, seniority}] -> who plays which buying role."""
    roles: dict[str, list] = {r: [] for r in cfg.pipeline.opportunities.committee_roles}
    for c in contacts:
        roles.setdefault(committee_role(c.get("seniority"), cfg), []).append(c["lead_id"])
    covered = [r for r, ids in roles.items() if ids]
    missing = [r for r, ids in roles.items() if not ids]
    return {"roles": roles, "covered": covered, "missing": missing, "size": len(contacts)}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def deal_stall(o: Opportunity, now: datetime, cfg) -> dict:
    if o.status != "open":
        return {"is_stalled": False, "rules": [], "details": [], "risk": 0, "days_over_sla": 0.0}
    sla = cfg.pipeline.stall.sla_days.get(o.stage)
    ref = max(x for x in (o.last_activity_at, o.stage_entered_at, o.opened_at) if x is not None)
    idle = age_days(now, ref)
    over = idle - sla if sla is not None else 0.0
    if sla is None or over <= 0:
        return {"is_stalled": False, "rules": [], "details": [], "risk": 0, "days_over_sla": 0.0}
    st = cfg.pipeline.stall
    risk = min(st.max_risk, st.weights.S1 + st.per_day_over_sla * over)
    return {"is_stalled": True, "rules": ["S1"], "risk": round(risk),
            "details": [f"No activity on the deal for {idle:.0f}d (stage SLA {sla}d)"], "days_over_sla": round(over, 2)}


def evaluate_opportunity(o: Opportunity, profile: Profile, events: list[Event], best: ScoreResult, members: list[dict],
                         now: datetime, ctx: LeadContext, cfg) -> dict:
    """Value, close probability, stall and buying committee of one deal at `now`.

    profile: the primary contact's profile (firmographics, seats, budget); events: the deal's events;
    best: the highest-scoring contact's score; members: [{lead_id, name, title, seniority}] of the deal's contacts.
    """
    acv = predict_acv(profile, events, cfg)
    if o.amount is not None:
        acv = {**acv, "acv": round(o.amount, 2), "p10": round(o.amount, 2), "p90": round(o.amount, 2),
               "factors": acv["factors"] + [{"key": "deal_amount", "label": "Amount on the deal", "value": o.amount,
                                             "kind": "override"}]}
    stall = deal_stall(o, now, cfg)
    comm = committee(members, cfg)
    if o.status == "won":
        close = {"p": 1.0, "factors": [{"key": "stage", "label": "Deal won", "logit": None}]}
    elif o.status == "lost":
        close = {"p": 0.0, "factors": [{"key": "stage", "label": "Deal lost", "logit": None}]}
    else:
        base = close_probability(o.stage, best, stall, ctx, cfg)
        extra = cfg.pipeline.opportunities.committee_coef * max(0, len(comm["covered"]) - 1)
        p = 1 / (1 + math.exp(-(_logit(base["p"]) + extra)))
        close = {"p": p, "factors": base["factors"] + [{
            "key": "committee", "label": f"Buying committee: {', '.join(r.replace('_', ' ') for r in comm['covered']) or 'none'}",
            "logit": round(extra, 3)}]}
    ev = acv["acv"] * close["p"]
    return {"acv": acv, "close": close, "expected_value": ev, "stall": stall, "committee": comm,
            "days_in_stage": age_days(now, o.stage_entered_at) if o.stage_entered_at else 0.0}
