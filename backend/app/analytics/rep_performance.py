"""Rep leaderboard: workload, pipeline, win rate, response time, neglect."""
from __future__ import annotations

from .response_time import response_times


def rep_performance(store, cfg, now) -> list[dict]:
    rt = {r["rep_id"]: r for r in response_times(store, cfg, now)["reps"]}
    out = []
    for rid, rep in store.reps.items():
        st = store.rep_stats[rid]
        owned = [store.leads[x] for x in store.owner_index.get(rid, ()) if store.leads[x].ev is not None]
        open_ = [l for l in owned if store.is_open(l)]
        live_won = sum(1 for l in owned if l.stage == "won")
        live_lost = sum(1 for l in owned if l.stage == "lost")
        wins, closed = sum(st["wins"].values()), sum(st["closed"].values())
        out.append({
            "rep_id": rid, "name": rep["name"], "profile": rep["profile"], "territories": rep["territories"],
            "industries": rep["industries"], "segments": rep["segments"], "tags": rep.get("tags", []),
            "open_leads": len(open_), "load": store.rep_load(rid), "capacity": rep["capacity_points"],
            "pipeline_ev": round(sum(l.ev.expected_value for l in open_), 2),
            "stalled": sum(1 for l in open_ if l.is_stalled),
            "won_live": live_won, "lost_live": live_lost, "wins_total": wins, "closed_total": closed,
            "win_rate": round(wins / closed, 4) if closed else None, "revenue": round(st["revenue"], 2),
            "median_first_response_min": rt[rid]["median_first_response_min"],
            "sla_attainment": rt[rid]["sla_attainment"], "neglect_count": st["neglect_count"],
            "reassigned_away": st["reassigned_away"], "assigned": st["assigned"],
        })
    out.sort(key=lambda r: (-(r["win_rate"] or 0), r["rep_id"]))
    return out
