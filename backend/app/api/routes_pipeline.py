"""Kanban pipeline with per-column totals, stalled overlay and stage history per card."""
from __future__ import annotations

from fastapi import APIRouter

from ..engine.types import iso
from .deps import state

router = APIRouter(prefix="/api")

COLUMNS = ["new", "contacted", "engaged", "qualified", "meeting", "proposal", "negotiation", "won", "lost", "nurture"]


@router.get("/pipeline")
async def pipeline(rep_id: str | None = None, source: str | None = None, include_disqualified: bool = False,
                   closed_limit: int = 40):
    async with state.lock:
        store = state.runtime.store
        cols = {c: [] for c in COLUMNS + (["disqualified"] if include_disqualified else [])}
        for l in store.leads.values():
            if l.ev is None or l.status == "merged" or l.stage not in cols:
                continue
            p = l.profile
            if rep_id and l.owner != rep_id:
                continue
            if source and p.source_primary != source:
                continue
            ev = l.ev
            cols[l.stage].append({
                "lead_id": l.lead_id, "name": p.name, "company": p.company, "score": round(ev.score.score, 1),
                "grade": ev.score.grade, "intent_level": ev.score.intent_level, "owner_rep_id": l.owner,
                "owner_name": store.rep_name(l.owner), "acv": ev.acv["acv"], "close_prob": round(ev.close["p"], 3),
                "expected_value": round(ev.expected_value, 2), "is_stalled": ev.stall["is_stalled"],
                "stall_rules": ev.stall["rules"], "stall_risk": ev.stall["risk"],
                "days_in_stage": round(ev.days_in_stage, 1), "source": p.source_primary,
                "updated_at": iso(l.last_eval_at),
                "history": [{"ts": iso(t["ts"]), "from": t["from_stage"], "to": t["to_stage"], "rule_id": t["rule_id"],
                             "reason": t["reason"], "mode": t["mode"]} for t in l.transitions[-8:]],
            })
        out = []
        for stage, cards in cols.items():
            cards.sort(key=lambda c: (-c["expected_value"], c["lead_id"]))
            if stage in ("won", "lost"):
                cards.sort(key=lambda c: c["updated_at"] or "", reverse=True)
            out.append({"stage": stage, "count": len(cards), "acv_total": round(sum(c["acv"] for c in cards), 2),
                        "ev_total": round(sum(c["expected_value"] for c in cards), 2),
                        "stalled": sum(1 for c in cards if c["is_stalled"]),
                        "cards": cards[:closed_limit] if stage in ("won", "lost") else cards})
        return {"columns": out}
