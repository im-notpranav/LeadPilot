"""Accounts (companies) and deals (opportunities).

Reads come from the in-memory projection; every change is an event on the deal's primary contact
(opportunity_created / opportunity_updated / deal_won / deal_lost), so deals replay like everything else.
Scope: you see an account or a deal when you can see at least one of its contacts.
"""
from __future__ import annotations

import re
import secrets
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import Principal
from ..engine.enrich import segment_for
from ..engine.opportunity import committee_role
from ..engine.types import iso
from .deps import state
from .security import user, visible_lead

router = APIRouter(prefix="/api")

KINDS = ("new_business", "expansion", "renewal")
OPEN_STAGES = ("qualified", "meeting", "proposal", "negotiation")


def _visible_opp(p: Principal, o) -> bool:
    store = state.runtime.store
    return any(p.can_see(store.leads.get(lid)) for lid in o.contact_ids)


def _opp_or_404(p: Principal, opp_id: str):
    o = state.runtime.store.opps.get(opp_id)
    if o is None or not _visible_opp(p, o):
        raise HTTPException(404, f"deal {opp_id} not found")
    return o


def _account_summary(account_id: str, contacts: list) -> dict:
    store = state.runtime.store
    cfg = state.runtime.cfg
    firm = next((l.profile for l in contacts if l.profile.employees is not None), contacts[0].profile)
    opps = [store.opps[i] for i in store.account_opps.get(account_id, []) if i in store.opps]
    evals = store.opp_evals
    open_opps = [o for o in opps if o.status == "open"]
    owners = sorted({l.owner for l in contacts if l.owner})
    last = max((l.ev.metrics.get("last_inbound_at") for l in contacts if l.ev and l.ev.metrics.get("last_inbound_at")),
               default=None)
    return {
        "account_id": account_id, "name": next((l.profile.company for l in contacts if l.profile.company), None),
        "domain": firm.domain, "industry": firm.industry, "employees": firm.employees,
        "segment": segment_for(firm.employees, cfg), "country": firm.hq_country or firm.country,
        "contacts": len(contacts), "open_deals": len(open_opps), "deals": len(opps),
        "pipeline_ev": round(sum(evals.get(o.opp_id, {}).get("expected_value", 0.0) for o in open_opps), 2),
        "pipeline_acv": round(sum((evals.get(o.opp_id) or {}).get("acv", {}).get("acv", 0.0) for o in open_opps), 2),
        "won_revenue": round(sum((evals.get(o.opp_id) or {}).get("acv", {}).get("acv", 0.0)
                                 for o in opps if o.status == "won"), 2),
        "best_score": round(max((l.ev.score.score for l in contacts if l.ev), default=0.0), 1),
        "owner_rep_ids": owners, "owner_names": [store.rep_name(r) for r in owners],
        "committee_covered": sorted({committee_role(l.profile.seniority, cfg) for l in contacts}),
        "last_inbound_at": iso(last),
    }


def _account_contacts(p: Principal, account_id: str) -> list:
    store = state.runtime.store
    contacts = [l for l in store.account_contacts(account_id) if l.ev is not None]
    if not contacts or not any(p.can_see(l) for l in contacts):
        return []
    return contacts


# ================================================================================================ accounts
@router.get("/accounts")
async def accounts(q: str | None = None, sort: str = "pipeline", limit: int = 200, p: Principal = Depends(user)):
    async with state.lock:
        store = state.runtime.store
        rows = []
        for account_id in list(store.account_index):
            contacts = _account_contacts(p, account_id)
            if not contacts:
                continue
            row = _account_summary(account_id, contacts)
            if q and q.lower() not in " ".join(str(row.get(k) or "") for k in ("name", "domain", "industry")).lower():
                continue
            rows.append(row)
    keys = {"pipeline": lambda r: (-r["pipeline_ev"], -r["best_score"]), "contacts": lambda r: (-r["contacts"], r["name"] or ""),
            "won": lambda r: (-r["won_revenue"], r["name"] or ""), "name": lambda r: (r["name"] or "").lower()}
    rows.sort(key=keys.get(sort, keys["pipeline"]))
    return {"total": len(rows), "items": rows[:min(limit, 1000)],
            "totals": {"pipeline_ev": round(sum(r["pipeline_ev"] for r in rows), 2),
                       "open_deals": sum(r["open_deals"] for r in rows),
                       "won_revenue": round(sum(r["won_revenue"] for r in rows), 2)}}


@router.get("/accounts/{account_id}")
async def account(account_id: str, p: Principal = Depends(user)):
    async with state.lock:
        store = state.runtime.store
        cfg = state.runtime.cfg
        contacts = _account_contacts(p, account_id)
        if not contacts:
            raise HTTPException(404, f"account {account_id} not found")
        summary = _account_summary(account_id, contacts)
        opps = [store.opps[i] for i in store.account_opps.get(account_id, []) if i in store.opps]
        people = []
        for l in sorted(contacts, key=lambda l: -l.ev.score.score):
            v = store.lead_view(l)
            v["role"] = committee_role(l.profile.seniority, cfg)
            v["visible"] = p.can_see(l)
            if not v["visible"]:                    # a colleague's contact: name and role only
                v = {k: v[k] for k in ("lead_id", "name", "title", "role", "visible", "stage", "owner_name")}
            people.append(v)
        firm = next((l.profile for l in contacts if l.profile.employees is not None), contacts[0].profile)
        return {**summary, "revenue_band": firm.revenue_band, "funding_stage": firm.funding_stage,
                "tech_stack": firm.tech_stack, "people": people,
                "opportunities": [store.opp_view(o) for o in reversed(opps) if _visible_opp(p, o)]}


# ================================================================================================ deals
@router.get("/opportunities")
async def opportunities(status: str = "all", owner: str | None = None, account_id: str | None = None,
                        closed_limit: int = 40, p: Principal = Depends(user)):
    async with state.lock:
        store = state.runtime.store
        stages = list(state.runtime.cfg.pipeline.opportunities.stages)
        cols = {s: [] for s in stages}
        for o in store.opps.values():
            if status != "all" and o.status != status:
                continue
            if account_id and o.account_key != account_id:
                continue
            if not _visible_opp(p, o):
                continue
            v = store.opp_view(o)
            if owner and v["owner_rep_id"] != owner:
                continue
            cols[o.stage].append(v)
    out = []
    for stage, cards in cols.items():
        if stage in ("won", "lost"):
            cards.sort(key=lambda c: c["closed_at"] or "", reverse=True)
        else:
            cards.sort(key=lambda c: (-c["expected_value"], c["opp_id"]))
        out.append({"stage": stage, "count": len(cards), "acv_total": round(sum(c["acv"] or 0 for c in cards), 2),
                    "ev_total": round(sum(c["expected_value"] for c in cards), 2),
                    "stalled": sum(1 for c in cards if c["is_stalled"]),
                    "cards": cards[:closed_limit] if stage in ("won", "lost") else cards})
    open_cols = [c for c in out if c["stage"] in OPEN_STAGES]
    return {"columns": out, "open_deals": sum(c["count"] for c in open_cols),
            "pipeline_ev": round(sum(c["ev_total"] for c in open_cols), 2),
            "pipeline_acv": round(sum(c["acv_total"] for c in open_cols), 2)}


@router.get("/opportunities/{opp_id}")
async def opportunity(opp_id: str, p: Principal = Depends(user)):
    async with state.lock:
        o = _opp_or_404(p, opp_id)
        return state.runtime.store.opp_view(o, detail=True)


def _clean_fields(body: dict) -> dict:
    out: dict = {}
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "a deal needs a name")
        out["name"] = name[:120]
    if body.get("amount") not in (None, ""):
        try:
            amount = float(body["amount"])
        except (TypeError, ValueError):
            raise HTTPException(422, "amount must be a number") from None
        if not 0 < amount < 1e10:
            raise HTTPException(422, "amount must be above zero")
        out["amount"] = round(amount, 2)
    if body.get("close_date"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(body["close_date"])):
            raise HTTPException(422, "close_date must be YYYY-MM-DD")
        try:
            date.fromisoformat(body["close_date"])
        except ValueError:
            raise HTTPException(422, "close_date is not a real date") from None
        out["close_date"] = body["close_date"]
    return out


@router.post("/opportunities")
async def create_opportunity(body: dict = Body(...), p: Principal = Depends(user)):
    lead = visible_lead(p, str(body.get("lead_id") or ""))
    if lead.status != "active":
        raise HTTPException(409, f"this lead is {lead.status}")
    kind = body.get("kind") or None
    if kind is not None and kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    oid = "O-" + secrets.token_hex(5)
    payload = {"opportunity_id": oid, **({"kind": kind} if kind else {}), **_clean_fields(body),
               "by": p.email or p.name}
    r = await state.bus.publish({"type": "opportunity_created", "actor": "rep", "rep_id": lead.owner,
                                 "lead_ref": {"lead_id": lead.lead_id}, "payload": payload})
    if r.get("status") != "processed":
        raise HTTPException(409, r.get("reason") or r.get("status"))
    async with state.lock:
        o = state.runtime.store.opps.get(oid)
        return state.runtime.store.opp_view(o, detail=True) if o else {"opp_id": oid}


@router.patch("/opportunities/{opp_id}")
async def update_opportunity(opp_id: str, body: dict = Body(...), p: Principal = Depends(user)):
    stages = state.runtime.cfg.pipeline.opportunities.stages
    async with state.lock:
        o = _opp_or_404(p, opp_id)
        primary = state.runtime.store.leads.get(o.primary_lead_id)
        target = primary if primary is not None and p.can_see(primary) else next(
            state.runtime.store.leads[i] for i in o.contact_ids if p.can_see(state.runtime.store.leads.get(i)))
    fields = _clean_fields(body)
    stage = body.get("stage")
    if stage is not None and stage not in stages:
        raise HTTPException(422, f"stage must be one of {', '.join(stages)}")
    if not fields and stage is None:
        raise HTTPException(422, "nothing to change")
    by = p.email or p.name
    base = {"actor": "rep", "rep_id": target.owner, "lead_ref": {"lead_id": target.lead_id}}
    if stage == "won" and o.status == "open":
        ev = {**base, "type": "deal_won", "payload": {"opportunity_id": opp_id, **fields, "by": by}}
    elif stage == "lost" and o.status == "open":
        ev = {**base, "type": "deal_lost", "payload": {"opportunity_id": opp_id, **fields, "by": by,
                                                       "lost_reason": str(body.get("lost_reason") or "unspecified")[:200]}}
    else:
        pl = {"opportunity_id": opp_id, **fields, "by": by}
        if stage is not None and stage != o.stage:
            pl.update(stage=stage, reason=str(body.get("reason") or "")[:200] or None)
            if stage == "lost":
                pl["lost_reason"] = str(body.get("lost_reason") or "unspecified")[:200]
        ev = {**base, "type": "opportunity_updated", "payload": {k: v for k, v in pl.items() if v is not None}}
    r = await state.bus.publish(ev)
    if r.get("status") != "processed":
        raise HTTPException(409, r.get("reason") or r.get("status"))
    async with state.lock:
        o = state.runtime.store.opps.get(opp_id)
        if o is None:
            raise HTTPException(409, "the deal changed while saving; reload")
        return state.runtime.store.opp_view(o, detail=True)
