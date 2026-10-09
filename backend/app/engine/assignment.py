"""Lead assignment and reassignment of neglected leads (pure)."""
from __future__ import annotations

from datetime import datetime

from .enrich import segment_for
from .types import age_days


def smoothed_win_rate(wins: int, closed: int, team_rate: float, cfg) -> float:
    s = cfg.assignment.win_rate_prior_strength
    team_rate = max(team_rate, 0.01)
    return (wins + s) / (closed + s / team_rate)


def lead_facts(profile, grade: str, intent_level: str, cfg) -> dict:
    region = profile.region
    loc = cfg.assignment.locale.get(region or "", {})
    return {"region": region, "industry": profile.industry, "employees": profile.employees,
            "segment": segment_for(profile.employees, cfg) or "smb", "grade": grade, "intent_level": intent_level,
            "languages": list(loc.get("languages", ["en"])), "tz": loc.get("tz")}


def _territory_ok(rep: dict, region: str | None) -> bool:
    return "global" in rep["territories"] or (region is not None and region in rep["territories"])


def _locale_fit(rep: dict, lead: dict, cfg) -> float:
    lf = cfg.assignment.locale_fit
    score = lf.language if set(rep.get("languages", [])) & set(lead["languages"]) else 0.0
    if lead["tz"] is not None and rep.get("tz") is not None:
        diff = abs(rep["tz"] - lead["tz"])
        diff = min(diff, 24 - diff)
        if diff <= lf.tz_close_hours:
            score += lf.tz_close
        elif diff <= lf.tz_near_hours:
            score += lf.tz_near
    return score


def choose_rep(lead: dict, reps: list[dict], rep_stats: dict, team_rate: float, cfg,
               exclude: tuple = ()) -> dict:
    """rep_stats[rep_id] = {load, last_assigned_at, wins: {segment: n}, closed: {segment: n}}"""
    a = cfg.assignment
    weight = a.load_weight[lead["grade"]]
    seg = lead["segment"]
    candidates = []
    for rep in reps:
        st = rep_stats.get(rep["rep_id"], {})
        load = st.get("load", 0)
        cap = rep["capacity_points"]
        wins = st.get("wins", {}).get(seg, 0)
        closed = st.get("closed", {}).get(seg, 0)
        industry_match = lead["industry"] is not None and lead["industry"] in rep["industries"]
        skill = a.skill.industry * industry_match + a.skill.segment * (seg in rep["segments"])
        wr = smoothed_win_rate(wins, closed, team_rate, cfg)
        headroom = max(0.0, min(1.0, 1 - load / cap)) if cap else 0.0
        locale = _locale_fit(rep, lead, cfg)
        sw = a.score_weights
        total = sw.skill_match * skill + sw.win_rate_segment * wr + sw.capacity_headroom * headroom + sw.locale_fit * locale
        candidates.append({
            "rep_id": rep["rep_id"], "name": rep["name"], "active": rep.get("active", True),
            "excluded": rep["rep_id"] in exclude, "territory_ok": _territory_ok(rep, lead["region"]),
            "capacity_ok": load + weight <= cap, "enterprise": "enterprise" in rep.get("tags", []),
            "industry_match": industry_match, "skill": round(skill, 3), "win_rate": round(wr, 3),
            "headroom": round(headroom, 3), "locale": round(locale, 3), "total": round(total, 4), "load": load,
            "capacity": cap, "last_assigned_at": st.get("last_assigned_at"), "territories": rep["territories"],
        })

    base = [c for c in candidates if c["active"] and not c["excluded"]]
    relaxed: list[str] = []
    eligible = [c for c in base if c["territory_ok"] and c["capacity_ok"]]
    if not eligible:
        eligible = [c for c in base if c["capacity_ok"]]
        relaxed.append("territory")
    if not eligible:
        eligible = list(base)
        relaxed.append("capacity")
    if not eligible:
        return {"rep_id": None, "reason": "No active rep available", "candidates": candidates, "relaxed": relaxed}

    ep = a.enterprise_preference
    prefer_ent = ((lead["grade"] == "A" or lead["intent_level"] == "hot")
                  and (lead["employees"] or 0) > ep.min_employees)
    if prefer_ent and any(c["enterprise"] for c in eligible):
        eligible = [c for c in eligible if c["enterprise"]]

    def sort_key(c):
        last = c["last_assigned_at"]
        return (-c["total"], last.timestamp() if isinstance(last, datetime) else float("-inf"), c["rep_id"])

    best = sorted(eligible, key=sort_key)[0]
    for c in candidates:
        c["eligible"] = c in eligible
        c["chosen"] = c is best
    first = best["name"].split()[0]
    spec = f"{lead['industry']} specialist" if best["industry_match"] else "generalist"
    terr = "/".join(best["territories"])
    reason = (f"Assigned to {first} ({spec}, {terr}, {best['win_rate']:.0%} win rate in {seg.replace('_', '-')}, "
              f"{best['headroom']:.0%} capacity free)")
    if prefer_ent:
        reason += "; enterprise rep preferred for a hot large account"
    if relaxed:
        reason += f"; relaxed constraint: {', '.join(relaxed)}"
    return {"rep_id": best["rep_id"], "reason": reason, "candidates": candidates, "relaxed": relaxed}


def first_touch_deadline(assigned_at: datetime, grade: str, cfg):
    from datetime import timedelta
    return assigned_at + timedelta(minutes=cfg.assignment.reassignment.first_touch_sla_minutes[grade])


def check_reassignment(lead: dict, now, cfg) -> dict | None:
    """lead: {owner, assigned_at, stage, grade, last_outbound_at, last_rep_activity_at}. Returns {rule, reason}."""
    r = cfg.assignment.reassignment
    owner = lead.get("owner")
    if not owner or owner == r.manager_queue_id or lead.get("assigned_at") is None:
        return None
    stage = lead["stage"]
    if stage in cfg.derived.terminal or stage == "nurture":
        return None
    assigned = lead["assigned_at"]
    last_out = lead.get("last_outbound_at")
    if last_out is None or last_out < assigned:
        minutes = (now - assigned).total_seconds() / 60
        sla = r.first_touch_sla_minutes[lead["grade"]]
        if minutes > sla:
            return {"rule": "R1", "reason": f"No first touch {minutes:.0f} min after assignment "
                                            f"(grade {lead['grade']} SLA {sla} min)"}
    if stage in r.stages_r2:
        # Neglect is measured from the latest of: rep activity, assignment, or entering the current stage.
        last_act = max([t for t in (lead.get("last_rep_activity_at"), assigned, lead.get("stage_entered_at"))
                        if t is not None])
        days = age_days(now, last_act)
        if days >= r.open_deal_neglect_days:
            return {"rule": "R2", "reason": f"Open {stage} deal with no rep activity for {days:.0f} days"}
    return None
