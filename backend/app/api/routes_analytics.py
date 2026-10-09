"""Analytics + quality review endpoints."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException

from ..analytics.calibration import score_calibration, train_model
from ..analytics.funnel import funnel
from ..analytics.rep_performance import rep_performance
from ..analytics.response_time import response_times
from ..analytics.source_quality import compute_source_quality
from ..engine.types import iso
from .deps import state

router = APIRouter(prefix="/api")


def _ser(d: dict) -> dict:
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in d.items()}


@router.get("/analytics/funnel")
async def a_funnel():
    async with state.lock:
        return funnel(state.runtime.store, state.runtime.cfg)


@router.get("/analytics/response-times")
async def a_response():
    async with state.lock:
        rt = state.runtime
        return response_times(rt.store, rt.cfg, rt.clock.now())


@router.get("/analytics/rep-performance")
async def a_reps():
    async with state.lock:
        rt = state.runtime
        return {"items": rep_performance(rt.store, rt.cfg, rt.clock.now())}


@router.get("/analytics/score-calibration")
async def a_calibration():
    # Fitting the model (and importing scikit-learn) takes seconds: do it off the event loop and outside the
    # lock. It reads only store.historical, which changes on reset alone; the result is cached on the store.
    await asyncio.to_thread(train_model, state.runtime.store)
    async with state.lock:
        return score_calibration(state.runtime.store)


@router.get("/analytics/source-quality")
async def a_sources(window_days: int = 30):
    async with state.lock:
        rt = state.runtime
        stats = compute_source_quality(rt.store, rt.cfg, rt.clock.now(), window_days=window_days)
        trend = defaultdict(list)
        for row in rt.store.source_daily[-30 * len(stats):]:
            trend[row["source_id"]].append({"date": row["date"], "quality_index": row["quality_index"],
                                            "fake_rate": row["fake_rate"], "dup_rate": row["dup_rate"],
                                            "sql_rate": row["sql_rate"], "flagged": row["flagged"]})
        rows = sorted(stats.values(), key=lambda s: -s["quality_index"])
        return {"window_days": window_days, "now": iso(rt.clock.now()), "sources": rows, "trend": trend}


@router.get("/quality/review-queue")
async def review_queue(status: str = "open"):
    async with state.lock:
        store = state.runtime.store
        items = []
        for item in store.review.values():
            if status != "all" and item["status"] != status:
                continue
            row = _ser(item)
            row["lead"] = _brief(store, item["lead_id"])
            row["candidate"] = _brief(store, item["candidate_id"]) if item.get("candidate_id") else None
            items.append(row)
        items.sort(key=lambda r: r["ts"], reverse=True)
        return {"items": items}


@router.post("/quality/review/{review_id}")
async def review(review_id: str, body: dict = Body(...)):
    store = state.runtime.store
    item = store.review.get(review_id)
    if item is None:
        raise HTTPException(404, "review item not found")
    if item["status"] != "open":
        raise HTTPException(409, "already resolved")
    decision = body.get("decision")
    base = {"actor": "manager", "rep_id": None}
    if item["kind"] == "duplicate" and decision == "merge":
        ev = {**base, "type": "merge_approved", "payload": {"lead_id": item["lead_id"], "candidate_id": item["candidate_id"],
                                                            "confidence": item["confidence"], "match_keys": item["match_keys"],
                                                            "review_id": review_id}}
    elif decision == "reject" and item["kind"] == "duplicate":
        ev = {**base, "type": "review_rejected", "payload": {"review_id": review_id}}
    elif item["kind"] == "suspicious" and decision == "approve":
        ev = {**base, "type": "quality_cleared", "lead_ref": {"lead_id": item["lead_id"]},
              "payload": {"review_id": review_id, "reviewed_by": body.get("reviewer", "manager")}}
    elif item["kind"] == "suspicious" and decision == "disqualify":
        ev = {**base, "type": "lead_disqualified", "lead_ref": {"lead_id": item["lead_id"]},
              "payload": {"reason": "Rejected in quality review", "review_id": review_id}}
    else:
        raise HTTPException(422, f"decision {decision!r} not valid for {item['kind']}")
    result = await state.bus.publish(ev)
    return {"review_id": review_id, "decision": decision, "result": result, "status": item["status"]}


@router.post("/quality/clear/{lead_id}")
async def clear_flag(lead_id: str, body: dict = Body(default={})):
    """Reviewer marks a fake/suspicious flag as a false positive: restores the lead (logged as an event)."""
    store = state.runtime.store
    lid = store.resolve_lead_id(lead_id)
    if not lid:
        raise HTTPException(404, "lead not found")
    return await state.bus.publish({"type": "quality_cleared", "actor": "manager", "lead_ref": {"lead_id": lid},
                                    "payload": {"reviewed_by": body.get("reviewer", "manager")}})


@router.get("/quality/quarantine")
async def quarantine():
    async with state.lock:
        store = state.runtime.store
        rows = []
        for l in store.leads.values():
            if l.status == "quarantined" and l.ev is not None:
                v = store.lead_view(l)
                v["signals"] = l.profile.fake_signals
                rows.append(v)
        rows.sort(key=lambda v: v["created_at"] or "", reverse=True)
        return {"items": rows}


@router.get("/quality/merges")
async def merges():
    async with state.lock:
        store = state.runtime.store
        out = []
        for m in reversed(store.merges[-200:]):
            row = _ser(m)
            row["survivor"] = _brief(store, m["survivor_id"])
            out.append(row)
        return {"items": out}


def _brief(store, lead_id: str | None) -> dict | None:
    if not lead_id or lead_id not in store.leads:
        return None
    l = store.leads[lead_id]
    p = l.profile
    if p is None:
        return {"lead_id": lead_id, "status": l.status}
    return {"lead_id": lead_id, "name": p.name, "email": p.email, "phone": p.phone_e164, "company": p.company,
            "source": p.source_primary, "status": l.status, "score": round(l.ev.score.score, 1) if l.ev else None,
            "fake_score": p.fake_score, "signals": [s["key"] for s in p.fake_signals]}
