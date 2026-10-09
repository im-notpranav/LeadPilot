"""Response-time analytics: first response (median, p90), SLA attainment by rep, engagement frequency."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from .funnel import countable


def _pct(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    vs = sorted(values)
    k = (len(vs) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return round(vs[lo] + (vs[hi] - vs[lo]) * (k - lo), 1)


def response_times(store, cfg, now) -> dict:
    sla = cfg.assignment.reassignment.first_touch_sla_minutes
    per = defaultdict(lambda: {"first": [], "reply": [], "met": 0, "total": 0})
    all_first = []
    for l in countable(store):
        m = l.ev.metrics
        rep = m.get("first_response_rep_id")
        fr = m.get("first_response_minutes")
        if fr is not None and rep:
            per[rep]["first"].append(fr)
            per[rep]["total"] += 1
            per[rep]["met"] += fr <= sla[l.ev.score.grade]
            all_first.append(fr)
        if l.owner and m.get("reply_response_minutes"):
            per[l.owner]["reply"].extend(m["reply_response_minutes"])
    reps = []
    for rid, rep in store.reps.items():
        d = per.get(rid, {"first": [], "reply": [], "met": 0, "total": 0})
        reps.append({"rep_id": rid, "name": rep["name"], "profile": rep["profile"], "n": len(d["first"]),
                     "median_first_response_min": _pct(d["first"], 50), "p90_first_response_min": _pct(d["first"], 90),
                     "sla_attainment": round(d["met"] / d["total"], 3) if d["total"] else None,
                     "median_reply_response_min": _pct(d["reply"], 50)})
    # engagement frequency: prospect events per day (last 14 days) and per lead-week by grade
    days = []
    start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = defaultdict(int)
    for e in store.log:
        if e.actor == "prospect" and not e.derived and e.ts >= start and e.ts <= now:
            buckets[e.ts.strftime("%Y-%m-%d")] += 1
    for i in range(14):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        days.append({"date": d, "prospect_events": buckets.get(d, 0)})
    by_grade = defaultdict(list)
    for l in countable(store):
        created = l.profile.created_at or l.created_at
        weeks = max(1 / 7, (now - created).total_seconds() / (7 * 86400)) if created else 1
        n = sum(1 for e in l.events if e.actor == "prospect" and not e.derived)
        by_grade[l.ev.score.grade].append(n / weeks)
    return {"overall": {"n": len(all_first), "median_first_response_min": _pct(all_first, 50),
                        "p90_first_response_min": _pct(all_first, 90)},
            "reps": reps, "daily_engagement": days,
            "events_per_lead_week_by_grade": {g: round(statistics.mean(v), 2) for g, v in sorted(by_grade.items())}}
