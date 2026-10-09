"""Queue priority (pure)."""
from __future__ import annotations


def urgency_points(due_in_minutes: float | None, cfg) -> float:
    pc = cfg.nba.priority
    if due_in_minutes is None:
        return 0.0
    if due_in_minutes <= pc.urgency_full_minutes:
        return 100.0
    if due_in_minutes >= pc.urgency_zero_minutes:
        return 0.0
    span = pc.urgency_zero_minutes - pc.urgency_full_minutes
    return 100.0 * (1 - (due_in_minutes - pc.urgency_full_minutes) / span)


def compute_priority(score: float, ev: float, p95_ev: float, due_in_minutes: float | None, action_label: str | None,
                     stall_risk: float, stage: str, sla_minutes_left: float | None, cfg) -> dict:
    pc = cfg.nba.priority
    w = pc.weights
    rank = cfg.derived.forward_rank
    norm_ev = min(1.0, ev / p95_ev) if p95_ev > 0 else 0.0
    urg = urgency_points(due_in_minutes, cfg)
    rescue = stall_risk if (stage in rank and rank[stage] >= rank["qualified"] and stage != "won") else 0.0
    parts = [
        ("score", w.score * score, f"Score {score:.0f}"),
        ("expected_value", w.expected_value * 100 * norm_ev, f"${ev / 1000:,.0f}k expected"),
        ("urgency", w.urgency * urg, action_label or "Action due"),
        ("stall_rescue", w.stall_rescue * rescue, f"Stall risk {stall_risk:.0f} on open deal"),
    ]
    bonus = 0.0
    if sla_minutes_left is not None and 0 <= sla_minutes_left < pc.sla_breach_window_minutes:
        bonus = pc.sla_breach_bonus
        parts.append(("sla", bonus, f"SLA breach in {sla_minutes_left:.0f} min"))
    total = sum(p[1] for p in parts)
    drivers = [{"key": k, "points": round(v, 1), "label": lbl} for k, v, lbl in sorted(parts, key=lambda p: -p[1]) if v > 0.05]
    return {"priority": round(total, 2), "drivers": drivers}
