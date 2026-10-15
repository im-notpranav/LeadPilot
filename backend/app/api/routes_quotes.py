"""Quotes on deals.

Every change is an event on the quote's contact (quote_created / quote_revised / quote_approved / proposal_sent /
deal_won / quote_declined / quote_voided, each with payload.opportunity_id and payload.quote_id), so quotes replay
like everything else. Sending a quote is the deal's proposal_sent; the buyer accepting it is the deal's deal_won.

The buyer opens the quote through its own link (/q/<token>) without signing in, and can accept or decline it there.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import Principal
from ..engine.quotes import EDIT_FIELDS, QuoteError, clean_lines, display_status
from .deps import state
from .routes_deals import _opp_or_404, _visible_opp
from .security import user

router = APIRouter(prefix="/api")
public = APIRouter(prefix="/api/public")

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
VIEW_EVERY_S = 6 * 3600          # a buyer re-opening the quote counts as a new view at most this often


# ================================================================================================ helpers
def _quote_or_404(p: Principal, quote_id: str):
    """(deal, quote) when the caller can see the deal."""
    store = state.runtime.store
    row = store.quote_rows.get(quote_id)
    o = store.opps.get(row["opp_id"]) if row else None
    q = o.quotes.get(quote_id) if o is not None else None
    if q is None or not _visible_opp(p, o):
        raise HTTPException(404, f"quote {quote_id} not found")
    return o, q


def _today() -> date:
    return state.runtime.clock.now().date()


def _fields(body: dict, partial: bool) -> dict:
    """Validate the editable fields of a quote (all of them on create, the ones given on an edit)."""
    cfg = state.runtime.cfg
    out: dict = {}
    if "title" in body or not partial:
        title = str(body.get("title") or "").strip()[:160]
        if partial and not title:
            raise HTTPException(422, "a quote needs a title")
        out["title"] = title or None
    if "lines" in body or not partial:
        try:
            out["lines"] = clean_lines(body.get("lines") or [], cfg)
        except QuoteError as e:
            raise HTTPException(422, str(e)) from None
        if not out["lines"]:
            raise HTTPException(422, "add at least one line")
    if "discount_pct" in body or not partial:
        try:
            d = float(body.get("discount_pct") or 0)
        except (TypeError, ValueError):
            raise HTTPException(422, "discount must be a number") from None
        if not 0 <= d <= 100:
            raise HTTPException(422, "discount must be between 0 and 100")
        out["discount_pct"] = round(d, 2)
    if "valid_until" in body or not partial:
        v = body.get("valid_until")
        if v in (None, ""):
            v = (_today() + timedelta(days=int(cfg.quotes.valid_days))).isoformat()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
            raise HTTPException(422, "valid_until must be YYYY-MM-DD")
        try:
            day = date.fromisoformat(str(v))
        except ValueError:
            raise HTTPException(422, "valid_until is not a real date") from None
        if day < _today():
            raise HTTPException(422, "valid_until is in the past")
        out["valid_until"] = str(v)
    for k in ("notes", "terms"):
        if k in body or (not partial and k == "notes"):
            out[k] = str(body.get(k) or "").strip()[:4000]
    if not partial and not body.get("terms"):
        out["terms"] = str(cfg.quotes.terms or "").strip()     # the terms are kept on the quote, as sent
    return out


async def _publish(o, q, typ: str, payload: dict, actor: str = "rep") -> None:
    lead_id = q.lead_id if q is not None else payload.pop("_lead_id")
    lead = state.runtime.store.leads.get(lead_id)
    r = await state.bus.publish({"type": typ, "actor": actor, "rep_id": lead.owner if lead else None,
                                 "lead_ref": {"lead_id": lead_id},
                                 "payload": {"opportunity_id": o.opp_id, **payload}})
    if r.get("status") != "processed":
        raise HTTPException(409, r.get("reason") or r.get("status"))


async def _view(opp_id: str, quote_id: str) -> dict:
    async with state.lock:
        store = state.runtime.store
        o = store.opps.get(opp_id)
        q = o.quotes.get(quote_id) if o is not None else None
        if q is None:
            raise HTTPException(409, "the deal changed while saving; reload")
        return store.quote_view(o, q)


def _email_ready() -> tuple[bool, str | None]:
    ch = state.notifications.channels
    if not ch.configured("email"):
        return False, "Set RESEND_API_KEY and LEADPILOT_EMAIL_FROM to email quotes."
    if not ch.public_url:
        return False, "Set LEADPILOT_PUBLIC_URL so the email can link to the quote."
    if not (state.settings.live or ch.in_demo):
        return False, "Demo mode does not email the made-up contacts (LEADPILOT_NOTIFY_IN_DEMO=1 to allow it)."
    return True, None


# ================================================================================================ rep side
@router.get("/quotes/catalog")
async def catalog(p: Principal = Depends(user)):
    cfg = state.runtime.cfg.quotes
    ok, why = _email_ready()
    return {"currency": cfg.currency, "valid_days": cfg.valid_days, "max_lines": cfg.max_lines,
            "max_discount_pct": cfg.approval.max_discount_pct, "terms": cfg.terms, "seller_name": cfg.seller_name,
            "catalog": list(cfg.catalog), "email": {"ready": ok, "reason": why},
            "today": _today().isoformat()}


@router.get("/quotes")
async def list_quotes(status: str | None = None, p: Principal = Depends(user)):
    """Quotes on the deals you can see, newest first. status=needs_approval lists the approval queue."""
    async with state.lock:
        store = state.runtime.store
        items = []
        for o in store.opps.values():
            if not o.quotes or not _visible_opp(p, o):
                continue
            for q in o.quotes.values():
                v = store.quote_view(o, q)
                if status and v["status"] != status:
                    continue
                items.append({k: v[k] for k in ("quote_id", "opp_id", "title", "status", "deal_name", "company",
                                                "recipient", "totals", "valid_until", "created_at", "created_by",
                                                "sent_at", "updated_at", "needs_approval", "approved")})
    items.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return {"total": len(items), "items": items[:500]}


@router.get("/quotes/{quote_id}")
async def get_quote(quote_id: str, p: Principal = Depends(user)):
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        return state.runtime.store.quote_view(o, q)


@router.post("/opportunities/{opp_id}/quotes")
async def create_quote(opp_id: str, body: dict = Body(...), p: Principal = Depends(user)):
    async with state.lock:
        store = state.runtime.store
        o = _opp_or_404(p, opp_id)
        if o.status != "open":
            raise HTTPException(409, f"this deal is {o.status}; reopen it to quote")
        lead_id = str(body.get("lead_id") or o.primary_lead_id)
        lead = store.leads.get(lead_id)
        if lead_id not in o.contact_ids or not p.can_see(lead):
            raise HTTPException(422, "send the quote to one of the deal's contacts you can see")
        sup = str(body.get("supersedes") or "") or None
        if sup and sup not in o.quotes:
            raise HTTPException(422, f"quote {sup} is not on this deal")
        fields = _fields(body, partial=False)
        fields["title"] = fields["title"] or f"{o.name} quote"
    qid = "Q-" + secrets.token_hex(4).upper()
    payload = {"quote_id": qid, **fields, "token": secrets.token_urlsafe(24), "by": p.email or p.name,
               **({"supersedes": sup} if sup else {}), "_lead_id": lead_id}
    await _publish(o, None, "quote_created", payload)
    return await _view(opp_id, qid)


@router.patch("/quotes/{quote_id}")
async def revise_quote(quote_id: str, body: dict = Body(...), p: Principal = Depends(user)):
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        if q.status != "draft":
            raise HTTPException(409, f"this quote is {q.status}; make a new version to change it")
        fields = _fields({k: body[k] for k in EDIT_FIELDS if k in body}, partial=True)
        if not fields:
            raise HTTPException(422, "nothing to change")
    await _publish(o, q, "quote_revised", {"quote_id": quote_id, **fields, "by": p.email or p.name})
    return await _view(o.opp_id, quote_id)


@router.post("/quotes/{quote_id}/approve")
async def approve_quote(quote_id: str, p: Principal = Depends(user)):
    if p.role not in ("admin", "manager"):
        raise HTTPException(403, "only a manager can approve a discount")
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        if q.status != "draft":
            raise HTTPException(409, f"this quote is {q.status}")
        if q.approved or not q.needs_approval:
            raise HTTPException(409, "this quote does not need approval")
        rev = q.rev
    await _publish(o, q, "quote_approved", {"quote_id": quote_id, "rev": rev, "by": p.email or p.name})
    return await _view(o.opp_id, quote_id)


@router.post("/quotes/{quote_id}/send")
async def send_quote(quote_id: str, body: dict = Body(default={}), p: Principal = Depends(user)):
    """Mark the quote sent (the deal moves to proposal and takes the quote's total). email=true also emails the
    contact a link to it."""
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        if o.status != "open":
            raise HTTPException(409, f"this deal is {o.status}")
        if q.status != "draft":
            raise HTTPException(409, f"this quote is already {q.status}")
        if not q.ready:
            raise HTTPException(409, f"the discount is above {state.runtime.cfg.quotes.approval.max_discount_pct}%: "
                                     "a manager has to approve it first")
        if q.valid_until and q.valid_until < _today().isoformat():
            raise HTTPException(409, "this quote has expired; change its date first")
        lead = state.runtime.store.leads.get(q.lead_id)
        to = lead.profile.email if lead is not None else None
        qc = state.runtime.cfg.quotes
        name = lead.profile.name if lead is not None else None
        n = {"title": f"Quote {q.quote_id}: {q.title}", "link": f"/q/{q.token}",
             "body": f"Hello{' ' + name if name else ''},\n\nHere is your quote from {qc.seller_name}: {q.title}, "
                     f"{qc.currency} {q.totals['total']:,.2f}, valid until {q.valid_until}. You can read it, and "
                     "accept or decline it, at the link below."}
        amount, rev = q.totals["total"], q.rev
    emailed = None
    if body.get("email"):
        ok, why = _email_ready()
        if not ok:
            raise HTTPException(409, why)
        if not to:
            raise HTTPException(409, "the contact has no email address")
        ch = state.notifications.channels
        async with ch.client() as client:
            res = await ch.send(client, "email", to, n)
        if res.get("status") != "sent":
            raise HTTPException(502, f"the email was not sent: {res.get('detail') or 'unknown error'}")
        emailed = to
    await _publish(o, q, "proposal_sent", {"quote_id": quote_id, "amount": amount, "rev": rev,
                                           "by": p.email or p.name, **({"emailed_to": emailed} if emailed else {})})
    return {**await _view(o.opp_id, quote_id), "emailed_to": emailed}


@router.post("/quotes/{quote_id}/void")
async def void_quote(quote_id: str, body: dict = Body(default={}), p: Principal = Depends(user)):
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        if q.status not in ("draft", "sent"):
            raise HTTPException(409, f"this quote is {q.status}")
    await _publish(o, q, "quote_voided", {"quote_id": quote_id, "reason": str(body.get("reason") or "")[:500] or None,
                                          "by": p.email or p.name})
    return await _view(o.opp_id, quote_id)


async def _accept(o, q, actor: str, accepted_by: dict) -> None:
    await _publish(o, q, "deal_won", {"quote_id": q.quote_id, "amount": q.totals["total"],
                                      "accepted_by": accepted_by}, actor=actor)


def _check_answerable(o, q) -> None:
    if q.status != "sent" or display_status(q, _today().isoformat()) != "sent":
        raise HTTPException(409, "this quote has expired" if q.status == "sent" else f"this quote is {q.status}")
    if o.status != "open":
        raise HTTPException(409, f"this deal is already {o.status}")


@router.post("/quotes/{quote_id}/accept")
async def record_accept(quote_id: str, body: dict = Body(default={}), p: Principal = Depends(user)):
    """The buyer accepted outside LeadPilot (signed PDF, email): record it. The deal is won at the quote's total."""
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        _check_answerable(o, q)
    await _accept(o, q, "rep", {"name": str(body.get("name") or "").strip()[:120] or None,
                                "recorded_by": p.email or p.name})
    return await _view(o.opp_id, quote_id)


@router.post("/quotes/{quote_id}/decline")
async def record_decline(quote_id: str, body: dict = Body(default={}), p: Principal = Depends(user)):
    async with state.lock:
        o, q = _quote_or_404(p, quote_id)
        _check_answerable(o, q)
    await _publish(o, q, "quote_declined", {"quote_id": quote_id, "reason": str(body.get("reason") or "")[:500] or None,
                                            "by": p.email or p.name})
    return await _view(o.opp_id, quote_id)


# ================================================================================================ buyer side
def _by_token(token: str):
    if not TOKEN_RE.fullmatch(token or ""):
        raise HTTPException(404, "quote not found")
    store = state.runtime.store
    ref = store.quote_tokens.get(token)
    o = store.opps.get(ref[0]) if ref else None
    q = o.quotes.get(ref[1]) if o is not None else None
    if q is None or q.token != token or q.status in ("draft", "void"):
        raise HTTPException(404, "quote not found")         # drafts and withdrawn quotes are not shown
    return o, q


def _buyer_view(o, q) -> dict:
    v = state.runtime.store.quote_view(o, q, buyer=True)
    return {**v, "seller_name": state.runtime.cfg.quotes.seller_name,
            "answerable": v["status"] == "sent" and o.status == "open"}


@public.get("/quotes/{token}")
async def buyer_quote(token: str, preview: bool = False):
    """The buyer opens their quote. Counts as a view (proposal_viewed) unless it is the rep's preview."""
    async with state.lock:
        o, q = _by_token(token)
        now = state.runtime.clock.now()
        count = (not preview and q.status == "sent"
                 and (q.last_viewed_at is None or (now - q.last_viewed_at).total_seconds() >= VIEW_EVERY_S))
    if count:
        await _publish(o, q, "proposal_viewed", {"quote_id": q.quote_id}, actor="prospect")
    async with state.lock:
        o, q = _by_token(token)
        return _buyer_view(o, q)


@public.post("/quotes/{token}/accept")
async def buyer_accept(token: str, body: dict = Body(default={})):
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(422, "type your name to accept")
    async with state.lock:
        o, q = _by_token(token)
        _check_answerable(o, q)
    await _accept(o, q, "prospect", {"name": name, "title": str(body.get("title") or "").strip()[:120] or None,
                                     "email": str(body.get("email") or "").strip()[:200] or None, "via": "link"})
    async with state.lock:
        o, q = _by_token(token)
        return _buyer_view(o, q)


@public.post("/quotes/{token}/decline")
async def buyer_decline(token: str, body: dict = Body(default={})):
    async with state.lock:
        o, q = _by_token(token)
        _check_answerable(o, q)
    await _publish(o, q, "quote_declined", {"quote_id": q.quote_id, "via": "link",
                                            "reason": str(body.get("reason") or "").strip()[:500] or None},
                   actor="prospect")
    async with state.lock:
        o, q = _by_token(token)
        return _buyer_view(o, q)

