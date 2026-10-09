"""Funnel: stage reach, stage-to-stage conversion, average time in stage (excludes fakes and merged duplicates)."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict


def countable(store):
    return [l for l in store.leads.values()
            if l.ev is not None and l.status != "merged" and l.profile.fake_status != "fake"]


def funnel(store, cfg) -> dict:
    order = list(cfg.pipeline.forward_order)
    leads = countable(store)
    reached: Counter = Counter()
    current: Counter = Counter()
    durations: dict[str, list] = defaultdict(list)
    for l in leads:
        seen = {"new", l.stage} | {t["to_stage"] for t in l.transitions}
        for s in order:
            if s in seen:
                reached[s] += 1
        current[l.stage] += 1
        prev_ts = l.profile.created_at or l.created_at
        for t in sorted(l.transitions, key=lambda t: t["ts"]):
            if prev_ts is not None:
                durations[t["from_stage"]].append((t["ts"] - prev_ts).total_seconds() / 3600)
            prev_ts = t["ts"]
    stages = [{"stage": s, "reached": reached[s], "current": current[s],
               "avg_hours_in_stage": round(statistics.mean(durations[s]), 1) if durations[s] else None} for s in order]
    conversions = [{"from": a, "to": b, "rate": round(reached[b] / reached[a], 4) if reached[a] else None}
                   for a, b in zip(order, order[1:])]
    side = {s: current[s] for s in ("nurture", "lost", "disqualified")}
    return {"total": len(leads), "stages": stages, "conversions": conversions, "side": side,
            "avg_hours_in_stage": {s: (round(statistics.mean(v), 1) if v else None) for s, v in durations.items()}}
