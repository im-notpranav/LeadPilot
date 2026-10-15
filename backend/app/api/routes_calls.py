"""Calls: a lead's calls (with the AI summary, transcript and recording), logging a call by hand, and fixing up
calls that arrived for a number no lead has yet.

Calls from the phone system arrive at /api/hooks/{connector id} (a "call" connector, see routes_connectors).
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import Principal
from ..calls.parse import CallParseError, manual_call
from ..calls.storage import StorageError
from .deps import state
from .security import manager, user, visible_lead

router = APIRouter(prefix="/api")


def _call_or_404(cid: str, p: Principal) -> dict:
    rec = state.calls.calls.get(cid)
    if rec is None:
        raise HTTPException(404, "call not found")
    if rec.get("lead_id"):
        store = state.runtime.store
        lead = store.leads.get(store.resolve_lead_id(rec["lead_id"]) or rec["lead_id"])
        if not p.can_see(lead):
            raise HTTPException(404, "call not found")
    elif p.role not in ("admin", "manager"):
        raise HTTPException(404, "call not found")
    return rec


@router.get("/calls/status")
async def status(p: Principal = Depends(user)):
    return state.calls.status()


@router.get("/calls")
async def recent(status: str | None = None, limit: int = 100, p: Principal = Depends(manager)):
    store = state.runtime.store
    out = []
    for rec in reversed(state.calls.calls.values()):
        if status and rec["status"] != status:
            continue
        lead = store.leads.get(rec["lead_id"]) if rec.get("lead_id") else None
        if lead is not None and not p.can_see(lead):
            continue
        v = state.calls.view(rec)
        v["lead_name"] = lead.profile.name if lead is not None and lead.profile else None
        out.append(v)
        if len(out) >= min(limit, 500):
            break
    return {"items": out, **state.calls.status()}


@router.get("/leads/{lead_id}/calls")
async def lead_calls(lead_id: str, p: Principal = Depends(user)):
    lead = visible_lead(p, lead_id)
    ids = {lead.lead_id, *((lead.profile.merged_ids or []) if lead.profile else [])}
    return {"items": [state.calls.view(r, full=True) for r in state.calls.for_lead(ids)], **state.calls.status()}


@router.post("/leads/{lead_id}/calls", status_code=202)
async def log_call(lead_id: str, body: dict = Body(...), p: Principal = Depends(user)):
    """A rep logs a call: notes or a pasted transcript, and how it went (or let the analysis decide)."""
    lead = visible_lead(p, lead_id)
    try:
        call = manual_call(lead.lead_id, p.rep_id or lead.owner, body, state.runtime.clock.now())
    except CallParseError as e:
        raise HTTPException(422, str(e)) from None
    rec, new = state.calls.receive(call)
    if not new:
        raise HTTPException(409, "this call was already logged")
    return state.calls.view(rec, full=True)


@router.get("/calls/{cid:path}/recording")
async def recording(cid: str, p: Principal = Depends(user)):
    rec = _call_or_404(cid, p)
    try:
        url = await state.calls.recording_link(rec)
    except StorageError as e:
        raise HTTPException(502, str(e)) from None
    if not url:
        raise HTTPException(404, "this call has no recording")
    return {"url": url, "stored": bool(rec.get("recording_path"))}


@router.post("/calls/{cid:path}/link")
async def link(cid: str, body: dict = Body(...), p: Principal = Depends(manager)):
    rec = _call_or_404(cid, p)
    if rec["status"] not in ("unmatched", "failed"):
        raise HTTPException(409, "only calls without a lead (or that failed) can be linked")
    lead = visible_lead(p, str(body.get("lead_id") or ""))
    return state.calls.view(await state.calls.link(rec["id"], lead.lead_id), full=True)


@router.post("/calls/{cid:path}/retry")
async def retry(cid: str, p: Principal = Depends(manager)):
    rec = _call_or_404(cid, p)
    if rec["status"] != "failed":
        raise HTTPException(409, "only failed calls can be retried")
    return state.calls.view(await state.calls.retry(rec["id"]), full=True)


@router.get("/calls/{cid:path}")
async def one(cid: str, p: Principal = Depends(user)):
    return state.calls.view(_call_or_404(cid, p), full=True)
