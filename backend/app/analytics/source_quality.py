"""Source quality report: volume, duplicate / fake / contact / SQL / win rates, response time, revenue, index, flags."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

QUALIFIED_PLUS = ("qualified", "meeting", "proposal", "negotiation", "won")


def reached_qualified(lead) -> bool:
    if lead.stage in QUALIFIED_PLUS:
        return True
    return any(t["to_stage"] in QUALIFIED_PLUS for t in lead.transitions)


def _source_rows(store, now: datetime, days: int | None) -> dict[str, list]:
    cutoff = now - timedelta(days=days) if days else None
    by_source: dict[str, list] = {s["source_id"]: [] for s in store.cfg.data.sources}
    for lead in store.leads.values():
        if lead.created_at is None or lead.created_at > now:
            continue
        if cutoff and lead.created_at < cutoff:
            continue
        by_source.setdefault(lead.source or "unknown", []).append(lead)
    return by_source


def _stats(leads: list, cost_per_lead: float) -> dict:
    volume = len(leads)
    dups = [l for l in leads if l.is_duplicate_capture]
    originals = [l for l in leads if not l.is_duplicate_capture and l.ev is not None]
    fakes = [l for l in originals if l.profile.fake_status == "fake"]
    real = [l for l in originals if l.profile.fake_status != "fake"]
    contacted = [l for l in real if l.ev.metrics.get("last_outbound_at") is not None]
    sqls = [l for l in real if reached_qualified(l)]
    won = [l for l in real if l.stage == "won"]
    lost = [l for l in real if l.stage == "lost"]
    frt = [l.ev.metrics["first_response_minutes"] for l in real if l.ev.metrics.get("first_response_minutes") is not None]
    revenue = sum(l.ev.acv["acv"] for l in won)
    n_real = len(real)
    return {
        "volume": volume,
        "duplicates": len(dups),
        "fakes": len(fakes),
        "dup_rate": len(dups) / volume if volume else 0.0,
        "fake_rate": len(fakes) / len(originals) if originals else 0.0,
        "contact_rate": len(contacted) / n_real if n_real else 0.0,
        "sql_rate": len(sqls) / n_real if n_real else 0.0,
        "sqls": len(sqls),
        "won": len(won),
        "lost": len(lost),
        "win_rate": len(won) / (len(won) + len(lost)) if (won or lost) else 0.0,
        "median_first_response_min": statistics.median(frt) if frt else None,
        "avg_score": statistics.mean(l.ev.score.score for l in real) if real else 0.0,
        "revenue": revenue,
        "cost": cost_per_lead * volume,
        "cost_per_sql": (cost_per_lead * volume / len(sqls)) if sqls else None,
    }


def compute_source_quality(store, cfg, now: datetime, window_days: int = 30) -> dict:
    sq = cfg.quality.source_quality
    costs = {s["source_id"]: s["cost_per_lead"] for s in cfg.data.sources}
    names = {s["source_id"]: s["name"] for s in cfg.data.sources}
    main = {sid: _stats(ls, costs.get(sid, 0)) for sid, ls in _source_rows(store, now, window_days).items()}
    last7 = {sid: _stats(ls, costs.get(sid, 0)) for sid, ls in _source_rows(store, now, 7).items()}
    total_real = sum(s["volume"] - s["duplicates"] - s["fakes"] for s in main.values())
    total_sql = sum(s["sqls"] for s in main.values())
    overall_sql = total_sql / total_real if total_real else 0.0
    max_sql = max([s["sql_rate"] for s in main.values()] + [1e-9])
    max_win = max([s["win_rate"] for s in main.values()] + [1e-9])
    w, fl = sq.weights, sq.flags
    out = {}
    for sid, s in main.items():
        qi = (w.sql_rate * s["sql_rate"] / max_sql + w.win_rate * s["win_rate"] / max_win
              + w.fake_free * (1 - s["fake_rate"]) + w.dup_free * (1 - s["dup_rate"]) + w.avg_score * s["avg_score"] / 100)
        reasons = []
        r7 = last7.get(sid, {})
        name = names.get(sid, sid)
        if r7.get("volume", 0) >= 3 and r7.get("fake_rate", 0) > fl.max_fake_rate:
            reasons.append(f"{name}: {r7['fake_rate']:.0%} fake in last 7 days")
        elif s["volume"] >= 3 and s["fake_rate"] > fl.max_fake_rate:
            reasons.append(f"{name}: {s['fake_rate']:.0%} fake in last {window_days} days")
        if r7.get("volume", 0) >= 3 and r7.get("dup_rate", 0) > fl.max_dup_rate:
            reasons.append(f"{name}: {r7['dup_rate']:.0%} duplicates in last 7 days")
        elif s["volume"] >= 3 and s["dup_rate"] > fl.max_dup_rate:
            reasons.append(f"{name}: {s['dup_rate']:.0%} duplicates in last {window_days} days")
        if s["volume"] >= fl.min_volume_for_sql and s["sql_rate"] < fl.min_sql_ratio * overall_sql:
            reasons.append(f"{name}: SQL rate {s['sql_rate']:.0%} vs {overall_sql:.0%} overall")
        out[sid] = {**s, "source_id": sid, "name": name, "quality_index": round(qi, 4), "flagged": bool(reasons),
                    "flag_reasons": reasons, "last7": r7, "window_days": window_days}
    return out
