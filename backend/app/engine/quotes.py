"""Quotes on deals, pure.

A quote belongs to one deal and is a fold over that deal's quote events, so replays rebuild it exactly:

  quote_created   a rep drafts a quote (lines, discount, validity, recipient contact)
  quote_revised   the draft is changed (only while it is a draft; each change is a new revision)
  quote_approved  a manager approves the current revision (needed when the discount is above the limit)
  proposal_sent   with payload.quote_id: the quote went to the buyer (the deal moves to proposal, its amount
                  becomes the quote's total)
  proposal_viewed with payload.quote_id: the buyer opened it
  deal_won        with payload.quote_id: the buyer accepted it (the deal is won; other open quotes are superseded)
  quote_declined  the buyer said no to this quote (the deal stays open)
  quote_voided    a rep withdrew it

Totals are computed from the lines, which carry their own prices, so a catalog change never alters a quote.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

QUOTE_TYPES = ("quote_created", "quote_revised", "quote_approved", "quote_declined", "quote_voided")
BILLING = ("recurring", "one_time")
OPEN_STATUSES = ("draft", "sent")
EDIT_FIELDS = ("title", "lines", "discount_pct", "valid_until", "notes", "terms")


class QuoteError(ValueError):
    pass


@dataclass
class Quote:
    quote_id: str
    opp_id: str
    lead_id: str                       # the contact it is addressed to
    created_at: datetime
    created_by: str | None = None
    title: str = "Quote"
    lines: list = field(default_factory=list)
    discount_pct: float = 0.0          # on the whole quote, after line discounts
    valid_until: str | None = None
    notes: str = ""
    terms: str = ""
    token: str | None = None           # the buyer's link
    totals: dict = field(default_factory=dict)
    needs_approval: bool = False       # the discount is above the limit (whether or not it was approved)
    rev: int = 1
    approved_rev: int | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    status: str = "draft"              # draft | sent | accepted | declined | void | superseded
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    sent_by: str | None = None
    viewed_at: datetime | None = None
    last_viewed_at: datetime | None = None
    views: int = 0
    accepted_at: datetime | None = None
    accepted_by: dict | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    voided_at: datetime | None = None
    void_reason: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    event_ids: list = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.approved_rev == self.rev

    @property
    def ready(self) -> bool:
        """Can be sent: a draft that is within the discount limit or approved at this revision."""
        return self.status == "draft" and (not self.needs_approval or self.approved)


# ------------------------------------------------------------------------------------------------ lines and totals
def _num(v, lo: float, hi: float) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and lo <= x <= hi else None


def clean_lines(raw, cfg, strict: bool = True) -> list[dict]:
    """Normalise quote lines. strict (the API): raise QuoteError on the first bad line. Not strict (the fold, which
    may see events from a webhook): drop bad lines."""
    if not isinstance(raw, list):
        if strict:
            raise QuoteError("lines must be a list")
        return []
    catalog = {p["sku"]: p for p in cfg.quotes.catalog}
    out: list[dict] = []
    for i, ln in enumerate(raw[: int(cfg.quotes.max_lines)] if not strict else raw):
        try:
            if not isinstance(ln, dict):
                raise QuoteError(f"line {i + 1}: must be an object")
            item = catalog.get(ln.get("sku")) if ln.get("sku") else None
            name = str(ln.get("name") or (item or {}).get("name") or "").strip()[:160]
            if not name:
                raise QuoteError(f"line {i + 1}: needs a name")
            qty = _num(ln.get("qty", 1), 0, 1e6)
            if not qty:
                raise QuoteError(f"line {i + 1}: quantity must be above zero")
            price = _num(ln.get("unit_price", (item or {}).get("price")), 0, 1e9)
            if price is None:
                raise QuoteError(f"line {i + 1}: unit price must be a number from 0")
            disc = _num(ln.get("discount_pct") or 0, 0, 100)
            if disc is None:
                raise QuoteError(f"line {i + 1}: discount must be between 0 and 100")
            billing = ln.get("billing") or (item or {}).get("billing") or "recurring"
            if billing not in BILLING:
                raise QuoteError(f"line {i + 1}: billing must be recurring or one_time")
            out.append({"sku": str(ln["sku"])[:40] if ln.get("sku") else None, "name": name,
                        "description": str(ln.get("description") or (item or {}).get("description") or "").strip()[:300],
                        "unit": str(ln.get("unit") or (item or {}).get("unit") or "").strip()[:40],
                        "qty": round(qty, 4), "unit_price": round(price, 2), "discount_pct": round(disc, 2),
                        "billing": billing})
        except QuoteError:
            if strict:
                raise
    if strict and len(out) > int(cfg.quotes.max_lines):
        raise QuoteError(f"a quote can have at most {cfg.quotes.max_lines} lines")
    return out


def totals(lines: list[dict], discount_pct: float) -> dict:
    """List price, line discounts, the quote discount, and what is left per billing type. `total` is the first-year
    value (recurring + one-time), which becomes the deal amount when the quote is sent."""
    k = 1 - (discount_pct or 0) / 100
    list_total = sum(ln["qty"] * ln["unit_price"] for ln in lines)
    net = [ln["qty"] * ln["unit_price"] * (1 - ln["discount_pct"] / 100) for ln in lines]
    subtotal = sum(net)
    recurring = sum(n for n, ln in zip(net, lines) if ln["billing"] == "recurring") * k
    one_time = sum(n for n, ln in zip(net, lines) if ln["billing"] == "one_time") * k
    total = recurring + one_time
    return {"list_total": round(list_total, 2), "line_discounts": round(list_total - subtotal, 2),
            "subtotal": round(subtotal, 2), "quote_discount": round(subtotal - total, 2),
            "recurring": round(recurring, 2), "one_time": round(one_time, 2), "total": round(total, 2),
            "effective_discount_pct": round((list_total - total) / list_total * 100, 2) if list_total else 0.0,
            "line_totals": [round(n, 2) for n in net]}


def _discount(v) -> float:
    return _num(v or 0, 0, 100) or 0.0


def _recompute(q: Quote, cfg) -> None:
    q.totals = totals(q.lines, q.discount_pct)
    q.needs_approval = q.totals["effective_discount_pct"] > float(cfg.quotes.approval.max_discount_pct) + 1e-9


# ------------------------------------------------------------------------------------------------ the fold
def _edit(q: Quote, pl: dict, cfg) -> None:
    if "title" in pl:
        q.title = str(pl.get("title") or "").strip()[:160] or q.title
    if "lines" in pl:
        q.lines = clean_lines(pl.get("lines"), cfg, strict=False)
    if "discount_pct" in pl:
        q.discount_pct = _discount(pl.get("discount_pct"))
    if "valid_until" in pl:
        q.valid_until = str(pl.get("valid_until") or "")[:10] or None
    if "notes" in pl:
        q.notes = str(pl.get("notes") or "")[:4000]
    if "terms" in pl:
        q.terms = str(pl.get("terms") or "")[:4000]
    _recompute(q, cfg)


def apply_quote_event(quotes: dict, opp_id: str, e, cfg) -> Quote | None:
    """Apply one event that carries payload.quote_id to the deal's quotes (dict quote_id -> Quote, in creation
    order). Returns the quote it changed, if any. Events that do not fit the quote's state are ignored, so an
    out-of-order or replayed event can never corrupt a quote."""
    pl = e.payload or {}
    qid = str(pl.get("quote_id") or "")
    if not qid:
        return None
    t = e.type
    if t == "quote_created":
        if qid in quotes:
            return None
        q = Quote(quote_id=qid, opp_id=opp_id, lead_id=e.lead_id, created_at=e.ts, created_by=pl.get("by"),
                  token=str(pl["token"]) if pl.get("token") else None, terms=str(cfg.quotes.terms or ""),
                  supersedes=str(pl["supersedes"]) if pl.get("supersedes") else None)
        _edit(q, pl, cfg)
        q.updated_at = e.ts
        q.event_ids.append(e.event_id)
        quotes[qid] = q
        old = quotes.get(q.supersedes) if q.supersedes else None
        if old is not None and old.status in OPEN_STATUSES:
            old.status, old.superseded_by, old.updated_at = "superseded", qid, e.ts
        return q
    q = quotes.get(qid)
    if q is None:
        return None
    if t == "quote_revised":
        if q.status != "draft":
            return None
        _edit(q, {k: pl[k] for k in EDIT_FIELDS if k in pl}, cfg)
        q.rev += 1
    elif t == "quote_approved":
        if q.status != "draft" or (pl.get("rev") is not None and pl.get("rev") != q.rev):
            return None
        q.approved_rev, q.approved_by, q.approved_at = q.rev, pl.get("by"), e.ts
    elif t == "proposal_sent":
        if q.status != "draft":
            return None
        q.status, q.sent_at, q.sent_by = "sent", e.ts, pl.get("by")
    elif t == "proposal_viewed":
        q.views += 1
        q.viewed_at = q.viewed_at or e.ts
        q.last_viewed_at = e.ts
    elif t == "deal_won":
        if q.status != "sent":
            return None
        q.status, q.accepted_at = "accepted", e.ts
        q.accepted_by = pl.get("accepted_by") if isinstance(pl.get("accepted_by"), dict) else None
        for other in quotes.values():
            if other is not q and other.status in OPEN_STATUSES:
                other.status, other.superseded_by, other.updated_at = "superseded", qid, e.ts
    elif t == "quote_declined":
        if q.status != "sent":
            return None
        q.status, q.declined_at = "declined", e.ts
        q.decline_reason = str(pl.get("reason") or "").strip()[:500] or None
    elif t == "quote_voided":
        if q.status not in OPEN_STATUSES:
            return None
        q.status, q.voided_at = "void", e.ts
        q.void_reason = str(pl.get("reason") or "").strip()[:500] or None
    else:
        return None
    q.updated_at = e.ts
    q.event_ids.append(e.event_id)
    return q


def display_status(q: Quote, today: str | None) -> str:
    """The status to show at `today` (YYYY-MM-DD): a sent quote past its date is expired; a draft above the
    discount limit waits for approval."""
    if q.status == "sent" and q.valid_until and today and today > q.valid_until:
        return "expired"
    if q.status == "draft" and q.needs_approval and not q.approved:
        return "needs_approval"
    return q.status
