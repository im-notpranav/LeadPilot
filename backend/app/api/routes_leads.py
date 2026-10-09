"""Leads, timeline, score history, manual actions, event ingestion, per-rep queue."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from ..engine.types import iso
from .deps import lead_or_404, state

router = APIRouter(prefix="/api")

SORTS = {"priority": lambda v: -v.get("priority", 0), "score": lambda v: -v.get("score", 0),
         "created": lambda v: v.get("created_at") or "", "ev": lambda v: -v.get("expected_value", 0)}


@router.post("/events")
async def ingest(body=Body(...)):
    events = body if isinstance(body, list) else [body]
    results = []
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("type"):
            raise HTTPException(422, "each event needs a 'type'")
        results.append(await state.bus.publish(ev))
    return {"results": results}


@router.get("/events")
async def list_events(lead_id: str | None = None, type: str | None = None, limit: int = 100):
    async with state.lock:
        log = state.runtime.store.log
        out = []
        for e in reversed(log):
            if lead_id and e.lead_id != lead_id:
                continue
            if type and e.type != type:
                continue
            out.append(e.to_dict())
            if len(out) >= limit:
                break
    return {"items": out}


@router.get("/leads")
async def list_leads(rep_id: str | None = None, stage: str | None = None, grade: str | None = None,
                     stalled: bool | None = None, q: str | None = None, source: str | None = None,
                     status: str | None = None, include_closed: bool = True, sort: str = "priority",
                     limit: int = 200, offset: int = 0):
    async with state.lock:
        store = state.runtime.store
        rows = [store.lead_view(l) for l in store.leads.values() if l.ev is not None and l.status != "merged"]
    if rep_id:
        rows = [r for r in rows if r["owner_rep_id"] == rep_id]
    if stage:
        stages = set(stage.split(","))
        rows = [r for r in rows if r["stage"] in stages]
    if grade:
        rows = [r for r in rows if r["grade"] in set(grade.split(","))]
    if stalled is not None:
        rows = [r for r in rows if r["is_stalled"] == stalled]
    if source:
        rows = [r for r in rows if r["source"] == source]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if not include_closed:
        rows = [r for r in rows if r["stage"] not in ("won", "lost", "disqualified")]
    if q:
        ql = q.lower()
        rows = [r for r in rows if any(ql in str(r.get(k) or "").lower() for k in ("name", "company", "email", "lead_id"))]
    rows.sort(key=SORTS.get(sort, SORTS["priority"]))
    return {"total": len(rows), "items": rows[offset: offset + limit]}


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    async with state.lock:
        store = state.runtime.store
        raw = store.leads.get(lead_id)
        if raw is not None and raw.status == "merged":
            return {"lead_id": lead_id, "status": "merged", "merged_into": store.resolve_lead_id(lead_id)}
        lead = lead_or_404(lead_id)
        view = store.lead_view(lead, detail=True)
        view["transitions"] = [_ser(t) for t in lead.transitions]
        view["assignments"] = [_ser({k: v for k, v in a.items()}) for a in lead.assignments]
        view["actions"] = [_action(a) for a in lead.actions[-15:]]
        view["stall_flags"] = [_ser(f) for f in lead.stall_flags]
        view["merges"] = [_ser(m) for m in store.merges if m["survivor_id"] == lead.lead_id]
        return view


@router.get("/leads/{lead_id}/timeline")
async def timeline(lead_id: str):
    async with state.lock:
        store = state.runtime.store
        lead = lead_or_404(lead_id)
        items = []
        for e in lead.events:
            items.append({"kind": "event", "ts": iso(e.ts), "event_id": e.event_id, "type": e.type, "actor": e.actor,
                          "rep_id": e.rep_id, "rep_name": store.rep_name(e.rep_id), "source": e.source,
                          "payload": e.payload, "derived": e.derived, "order": 0})
        for r in lead.score_history:
            items.append({"kind": "score", "ts": iso(r["ts"]), "event_id": r["event_id"], "event_type": r["event_type"],
                          "old": round(r["old_score"], 2), "new": round(r["new_score"], 2), "delta": round(r["delta"], 2),
                          "summary": r["summary"], "contributions": _contribs(r["contributions"])[:6], "order": 1})
        for t in lead.transitions:
            items.append({"kind": "stage", **_ser(t), "order": 2})
        for a in lead.assignments:
            items.append({"kind": "assignment", "ts": iso(a["ts"]), "rep_id": a["rep_id"],
                          "rep_name": store.rep_name(a["rep_id"]), "previous_rep_id": a["previous_rep_id"],
                          "previous_rep_name": store.rep_name(a["previous_rep_id"]), "type": a["type"],
                          "rule_id": a["rule_id"], "reason": a["reason"], "order": 3})
        for act in lead.actions:
            items.append({"kind": "action", **_action(act), "ts": iso(act["ts"]), "order": 4})
        for f in lead.stall_flags:
            if f.get("cleared_at") is None or f.get("ts_detected"):
                items.append({"kind": "stall", **_ser(f), "ts": iso(f["ts_detected"]), "order": 5})
        for m in store.merges:
            if m["survivor_id"] == lead.lead_id:
                items.append({"kind": "merge", **_ser(m), "order": 6})
        items.sort(key=lambda x: (x["ts"] or "", x["order"]))
        return {"lead_id": lead.lead_id, "items": items}


@router.get("/leads/{lead_id}/score-history")
async def score_history(lead_id: str):
    async with state.lock:
        lead = lead_or_404(lead_id)
        return {"lead_id": lead.lead_id, "points": [
            {"id": r["id"], "ts": iso(r["ts"]), "score": round(r["new_score"], 2), "old": round(r["old_score"], 2),
             "delta": round(r["delta"], 2), "event_id": r["event_id"], "event_type": r["event_type"],
             "summary": r["summary"], "grade": r.get("grade"), "intent_level": r.get("intent_level"),
             "parts": r.get("parts"), "contributions": _contribs(r["contributions"])} for r in lead.score_history]}


async def _manual(lead_id: str, type_: str, payload: dict, actor: str = "rep", rep_id: str | None = None) -> dict:
    lead = lead_or_404(lead_id)
    ev = {"type": type_, "actor": actor, "rep_id": rep_id or lead.owner, "lead_ref": {"lead_id": lead.lead_id},
          "payload": payload}
    return await state.bus.publish(ev)


@router.post("/leads/{lead_id}/override-stage")
async def override_stage(lead_id: str, body: dict = Body(...)):
    if body.get("to_stage") not in state.runtime.cfg.pipeline.stages:
        raise HTTPException(422, "invalid to_stage")
    return await _manual(lead_id, "stage_override", {"to_stage": body["to_stage"], "reason": body.get("reason")},
                         actor="manager")


@router.post("/leads/{lead_id}/disqualify")
async def disqualify(lead_id: str, body: dict = Body(default={})):
    return await _manual(lead_id, "lead_disqualified", {"reason": body.get("reason") or "Disqualified by rep"})


@router.post("/leads/{lead_id}/assign")
async def assign(lead_id: str, body: dict = Body(...)):
    rep = body.get("rep_id")
    if rep not in state.runtime.store.reps:
        raise HTTPException(422, "unknown rep_id")
    return await _manual(lead_id, "manual_assign", {"rep_id": rep, "reason": body.get("reason")}, actor="manager",
                         rep_id=rep)


@router.post("/actions/{action_id}/done")
async def action_done(action_id: str):
    store = state.runtime.store
    for lead in store.leads.values():
        for a in lead.actions:
            if a["id"] == action_id:
                comp = a.get("completion") or {}
                if not comp.get("type"):
                    raise HTTPException(400, "this action has no completion event")
                if a["status"] != "open":
                    raise HTTPException(409, f"action is {a['status']}")
                ev = {"type": comp["type"], "actor": "rep", "rep_id": lead.owner or a.get("rep_id"),
                      "lead_ref": {"lead_id": lead.lead_id}, "payload": {**comp.get("payload", {}), "action_id": action_id}}
                return await state.bus.publish(ev)
    raise HTTPException(404, "action not found")


@router.get("/queue/{rep_id}")
async def queue(rep_id: str, limit: int = 100):
    async with state.lock:
        store = state.runtime.store
        now = state.runtime.clock.now()
        rows = []
        for l in store.leads.values():
            if l.ev is None or not store.is_open(l):
                continue
            if rep_id != "all" and l.owner != rep_id:
                continue
            v = store.lead_view(l)
            act = l.open_action()
            v["action_due_minutes"] = round((act["due_at"] - now).total_seconds() / 60, 1) if act else None
            v["sla_minutes_left"] = round((l.first_touch_deadline - now).total_seconds() / 60, 1) \
                if l.first_touch_deadline else None
            rows.append(v)
    rows.sort(key=lambda v: -v["priority"])
    return {"rep_id": rep_id, "rep_name": store.rep_name(rep_id) if rep_id != "all" else "All reps",
            "now": iso(now), "total": len(rows), "items": rows[:limit]}


def _ser(d: dict) -> dict:
    from datetime import datetime
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in d.items()}


def _action(a: dict) -> dict:
    out = _ser({k: a.get(k) for k in ("id", "rule_id", "action", "channel", "due_at", "urgency", "reason", "template",
                                      "status", "closed_at", "closed_by_event_id", "rep_id", "ts")})
    out["completion"] = a.get("completion")
    out["alternates"] = [{k: x.get(k) for k in ("rule_id", "action", "reason", "due_minutes", "urgency")}
                         for x in a.get("alternates", [])]
    return out


def _contribs(cs: list) -> list:
    out = []
    for c in cs:
        out.append({"key": c["key"], "category": c["category"], "delta": round(c["delta"], 2), "reason": c["reason"],
                    "text": c.get("text"), "evidence": c.get("evidence", [])})
    return out
