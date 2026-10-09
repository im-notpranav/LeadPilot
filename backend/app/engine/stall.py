"""Stall detection (pure). Stalled is an overlay flag, not a stage; it clears on the next prospect inbound."""
from __future__ import annotations

from .types import Event, LeadContext, age_days, age_hours, parse_ts


def detect_stall(stage: str, metrics: dict, events: list[Event], now, ctx: LeadContext, cfg) -> dict:
    st = cfg.pipeline.stall
    result = {"is_stalled": False, "rules": [], "details": [], "risk": 0, "days_over_sla": 0.0, "sla_days": None}
    if stage not in st.sla_days:
        return result
    sla = st.sla_days[stage]
    result["sla_days"] = sla
    dsi = metrics.get("days_since_last_inbound") or 0.0
    days_over = max(0.0, dsi - sla)
    result["days_over_sla"] = days_over
    rules: list[tuple[str, str]] = []

    last_in = metrics.get("last_inbound_at")
    in_grace = last_in is not None and age_hours(now, last_in) < st.grace_hours_after_inbound
    if dsi > sla:
        rules.append(("S1", f"No prospect activity for {dsi:.0f}d (SLA {sla}d in {stage})"))
    if not in_grace:
        # S2: open task overdue, or a next-best-action that expired undone
        open_tasks: dict[str, Event] = {}
        for e in events:
            if e.ts > now:
                break
            pl = e.payload or {}
            if e.type == "task_created" and pl.get("task_id"):
                open_tasks[pl["task_id"]] = e
            elif e.type == "task_completed" and pl.get("task_id"):
                open_tasks.pop(pl["task_id"], None)
        overdue = []
        for tid, e in open_tasks.items():
            due = (e.payload or {}).get("due_at")
            if due and age_hours(now, parse_ts(due)) > st.overdue_task_hours:
                overdue.append(tid)
        last_out = metrics.get("last_outbound_at")
        expired = [ts for ts in ctx.expired_actions
                   if ts <= now and age_days(now, ts) <= st.expired_action_lookback_days
                   and (last_out is None or ts > last_out)]
        if overdue:
            rules.append(("S2", f"{len(overdue)} task(s) overdue by more than {st.overdue_task_hours}h"))
        elif expired:
            rules.append(("S2", f"{len(expired)} recommended action(s) expired undone"))
        # S3: engagement velocity drop
        e7, prev7 = metrics.get("engagement_7d", 0), metrics.get("engagement_prev_7d", 0)
        if prev7 >= st.velocity_min_prev and e7 < st.velocity_ratio * prev7:
            rules.append(("S3", f"Engagement fell from {prev7} to {e7} events/week"))
        # S4: ghosting
        streak = metrics.get("unanswered_outbound_streak", 0)
        if streak >= 3:
            rules.append(("S4", f"{streak} follow-ups unanswered"))
        # S5: meeting held but no next step
        last_meeting = None
        next_step_after = False
        for e in events:
            if e.ts > now:
                break
            if e.type == "meeting_held":
                last_meeting, next_step_after = e, False
            elif e.type in ("meeting_scheduled", "proposal_sent", "contract_sent") and last_meeting is not None:
                next_step_after = True
        if last_meeting and not next_step_after and age_days(now, last_meeting.ts) > st.no_next_step_days:
            rules.append(("S5", f"Meeting {age_days(now, last_meeting.ts):.0f}d ago with no next step booked"))

    if rules:
        risk = sum(st.weights[r] for r, _ in rules) + st.per_day_over_sla * days_over
        result.update(is_stalled=True, rules=[r for r, _ in rules], details=[d for _, d in rules],
                      risk=int(min(st.max_risk, round(risk))))
    return result
