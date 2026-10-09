"""Deal value prediction and close probability (pure). Every term is returned as a factor."""
from __future__ import annotations

import math

from .intent import intent_level_index
from .types import Event, LeadContext, Profile, ScoreResult


def predict_acv(p: Profile, events: list[Event], cfg) -> dict:
    pc = cfg.pipeline.prediction
    band = p.employee_band or pc.default_band
    base = float(pc.base_acv[band])
    factors = [{"key": "base", "label": f"Base ACV for {band} employees", "value": base, "kind": "base"}]
    industry = p.industry or "other"
    mult = pc.industry_multiplier.get(industry, pc.industry_multiplier["other"])
    acv = base * mult
    factors.append({"key": "industry", "label": f"Industry {industry}", "value": mult, "kind": "multiplier"})

    if any(e.type == "page_view" and (e.payload or {}).get("page_category") == "enterprise_plan" for e in events):
        acv *= pc.enterprise_plan_multiplier
        factors.append({"key": "enterprise_plan", "label": "Viewed enterprise plan",
                        "value": pc.enterprise_plan_multiplier, "kind": "multiplier"})
    if p.seats:
        seat_value = p.seats * pc.per_seat_price
        if seat_value > acv:
            factors.append({"key": "seats", "label": f"{p.seats} seats x ${pc.per_seat_price}", "value": seat_value,
                            "kind": "override"})
            acv = seat_value
    modeled = acv
    if p.budget:
        capped = min(p.budget, pc.budget_cap_ratio * modeled)
        factors.append({"key": "budget", "label": f"Stated budget ${p.budget:,.0f} (cap {pc.budget_cap_ratio}x model)",
                        "value": capped, "kind": "override"})
        acv = capped
    # A quoted/contracted/won amount is the best evidence of all.
    for e in reversed(events):
        amt = (e.payload or {}).get("amount")
        if e.type in ("deal_won", "contract_sent", "proposal_sent") and amt:
            acv = float(amt)
            factors.append({"key": "quoted", "label": f"Amount on {e.type.replace('_', ' ')}", "value": acv,
                            "kind": "override"})
            break
    return {"acv": round(acv, 2), "p10": round(acv * pc.range.p10, 2), "p90": round(acv * pc.range.p90, 2),
            "factors": factors}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def close_probability(stage: str, score: ScoreResult, stall: dict, ctx: LeadContext, cfg) -> dict:
    cp = cfg.pipeline.close_probability
    if stage == "won":
        return {"p": 1.0, "factors": [{"key": "stage", "label": "Deal won", "logit": None}]}
    if stage in ("lost", "disqualified"):
        return {"p": 0.0, "factors": [{"key": "stage", "label": f"Stage {stage}", "logit": None}]}
    prior = cp.stage_prior.get(stage, cp.stage_prior["new"])
    c = cp.coef
    rep_wr = ctx.rep_segment_win_rate if ctx.rep_segment_win_rate is not None else ctx.team_win_rate
    lvl = intent_level_index(score.intent_level, cfg)
    terms = [
        ("stage", f"Stage prior {stage} {prior:.0%}", _logit(prior)),
        ("score", f"Score {score.score:.0f} vs 50", c.score * (score.score - 50)),
        ("intent", f"Intent {score.intent_level}", c.intent_level * (lvl - 2)),
        ("rep", f"Owner win rate {rep_wr:.0%} vs team {ctx.team_win_rate:.0%}", c.rep_win_rate * (rep_wr - ctx.team_win_rate)),
        ("stalled", "Stalled" if stall.get("is_stalled") else "Not stalled", c.stalled * (1 if stall.get("is_stalled") else 0)),
        ("sla", f"{stall.get('days_over_sla', 0):.0f}d over stage SLA", c.days_over_sla * stall.get("days_over_sla", 0)),
        ("source", f"Source quality {ctx.source_quality_index:.2f}", c.source_quality * (ctx.source_quality_index - 0.5)),
    ]
    z = sum(t[2] for t in terms)
    p = 1 / (1 + math.exp(-z))
    return {"p": p, "factors": [{"key": k, "label": lbl, "logit": round(v, 3)} for k, lbl, v in terms]}
