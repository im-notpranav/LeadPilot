"""What-if testing: replay the whole event log under draft rules in a scratch engine and compare the outcome with
what the active rules produce today, before anything is switched.

Both sides are replayed in scratch engines from the same snapshot of the log, with the clock frozen at the moment
the snapshot was taken: the active rules (what an activation of them would give now, which is the live state with
every deal re-evaluated as of now) and the draft rules (exactly what activating them would give). Nothing is shared
with the live engine and nothing is written.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import Counter
from datetime import datetime

from .engine.types import iso

log = logging.getLogger("leadpilot.whatif")

GRADES = ("A", "B", "C", "D")
SAMPLE = 200            # changed leads / deals listed per category (the counts are always complete)
KEEP = 10               # finished runs kept in memory
CLOSED = ("won", "lost", "disqualified")


class FrozenClock:
    """The scratch engine's clock: always the moment the snapshot was taken."""

    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now


# ================================================================================================ snapshot
def snapshot(store) -> dict:
    """The outcome the rules decide, per lead and per deal. Cheap: called under the API lock."""
    leads = {}
    for l in store.leads.values():
        if l.ev is None:
            continue
        p, ev, act = l.profile, l.ev, l.open_action()
        leads[l.lead_id] = {
            "name": p.name if p else None, "company": p.company if p else None, "status": l.status,
            "merged_into": l.merged_into, "grade": ev.score.grade, "score": round(ev.score.score, 1),
            "stage": ev.stage, "owner": l.owner, "stalled": bool(ev.stall["is_stalled"]),
            "action": act["rule_id"] if act else None, "action_text": act["action"] if act else None,
            "expected_value": round(ev.expected_value, 2),
        }
    deals = {}
    for o in store.opps.values():
        e = store.opp_evals.get(o.opp_id) or {}
        deals[o.opp_id] = {
            "name": o.name, "stage": o.stage, "status": o.status,
            "value": round(e.get("expected_value", 0.0), 2), "chance": round(e["close"]["p"], 4) if e else None,
            "stalled": bool(e and e["stall"]["is_stalled"]),
        }
    reps = {rid: r["name"] for rid, r in store.reps.items()}
    reps[store.cfg.assignment.reassignment.manager_queue_id] = "Manager queue"
    return {"leads": leads, "deals": deals, "reps": reps}


def replay_under(cfg, raw: list[dict], historical: list[dict], now: datetime, progress=None) -> dict:
    """Process `raw` under `cfg` in a scratch engine as of `now`, and snapshot the result."""
    from .persistence import NullPersistence
    from .processor import Processor
    from .store import Store
    store = Store(cfg)
    store.historical = list(historical)
    store.reset_projections()                      # folds the closed-deal history into rep stats
    proc = Processor(cfg, store, FrozenClock(now), NullPersistence())
    proc.hooks_enabled, proc.broadcast, proc.autoflush = False, False, False
    proc._replaying = True
    proc._dirty_accounts = set()
    store.raw_log = [dict(r) for r in raw]
    total = len(raw)
    for i, r in enumerate(store.raw_log):
        proc.handle(r)
        if progress and i % 250 == 0:
            progress(i, total)
    proc._replaying = False
    for key in sorted(proc._dirty_accounts):
        proc._rebuild_account(key, now)
    if progress:
        progress(total, total)
    return snapshot(store)


# ================================================================================================ compare
def _grade_rank(g: str | None) -> int:
    return GRADES.index(g) if g in GRADES else len(GRADES)


def _live(row: dict | None) -> bool:
    return row is not None and row["status"] != "merged"


def compare(before: dict, after: dict) -> dict:
    """Every outcome that differs between the two snapshots, as counts plus a sample of the leads and deals."""
    reps = {**before["reps"], **after["reps"]}
    rep = lambda r: reps.get(r, r) if r else None   # noqa: E731
    bl, al = before["leads"], after["leads"]
    ids = sorted(set(bl) | set(al))
    out_leads: dict[str, list] = {"grade": [], "stage": [], "owner": [], "action": [], "quality": []}
    up = down = 0
    for lid in ids:
        b, a = bl.get(lid), al.get(lid)
        name = (a or b)["name"]
        base = {"lead_id": lid, "name": name, "company": (a or b)["company"]}
        if _live(b) != _live(a) or (b and a and b["status"] != a["status"]):
            out_leads["quality"].append({**base, "before": _status(b), "after": _status(a)})
        if not (_live(b) and _live(a)):
            continue
        if b["grade"] != a["grade"]:
            up += _grade_rank(a["grade"]) < _grade_rank(b["grade"])
            down += _grade_rank(a["grade"]) > _grade_rank(b["grade"])
            out_leads["grade"].append({**base, "before": b["grade"], "after": a["grade"],
                                       "score_before": b["score"], "score_after": a["score"]})
        if b["stage"] != a["stage"]:
            out_leads["stage"].append({**base, "before": b["stage"], "after": a["stage"]})
        if b["owner"] != a["owner"]:
            out_leads["owner"].append({**base, "before": rep(b["owner"]), "after": rep(a["owner"])})
        if b["action"] != a["action"] and b["stage"] not in CLOSED:
            out_leads["action"].append({**base, "before": b["action_text"], "after": a["action_text"],
                                        "rule_before": b["action"], "rule_after": a["action"]})

    bd, ad = before["deals"], after["deals"]
    out_deals: dict[str, list] = {"opened": [], "closed": [], "stage": []}
    for oid in sorted(set(bd) | set(ad)):
        b, a = bd.get(oid), ad.get(oid)
        if b is None or a is None:
            out_deals["opened" if a else "closed"].append({"opp_id": oid, "name": (a or b)["name"],
                                                           "stage": (a or b)["stage"], "value": (a or b)["value"],
                                                           "exists": "draft only" if a else "active only"})
        elif b["stage"] != a["stage"]:
            out_deals["stage"].append({"opp_id": oid, "name": a["name"], "before": b["stage"], "after": a["stage"],
                                       "value_before": b["value"], "value_after": a["value"]})

    def dist(rows: dict, key: str, keep=lambda r: True) -> dict:
        return dict(Counter(r[key] for r in rows.values() if _live(r) and keep(r)))

    def deal_totals(rows: dict) -> dict:
        open_ = [r for r in rows.values() if r["status"] == "open"]
        return {"deals": len(rows), "open": len(open_), "won": sum(r["status"] == "won" for r in rows.values()),
                "lost": sum(r["status"] == "lost" for r in rows.values()),
                "stalled": sum(r["stalled"] for r in open_), "pipeline": round(sum(r["value"] for r in open_), 2)}

    def lead_totals(rows: dict) -> dict:
        live = [r for r in rows.values() if _live(r)]
        return {"leads": len(live), "quarantined": sum(r["status"] == "quarantined" for r in live),
                "merged": sum(r["status"] == "merged" for r in rows.values()),
                "stalled": sum(r["stalled"] for r in live if r["stage"] not in CLOSED)}

    counts = {**{k: len(v) for k, v in out_leads.items()},
              **{f"deals_{k}": len(v) for k, v in out_deals.items()}, "grade_up": up, "grade_down": down}
    return {
        "counts": counts,
        "unchanged": not any(counts[k] for k in counts if k not in ("grade_up", "grade_down")),
        "grades": {"before": dist(bl, "grade"), "after": dist(al, "grade")},
        "stages": {"before": dist(bl, "stage"), "after": dist(al, "stage")},
        "owners": {"before": _named(dist(bl, "owner"), rep), "after": _named(dist(al, "owner"), rep)},
        "leads": {"before": lead_totals(bl), "after": lead_totals(al)},
        "deals": {"before": deal_totals(bd), "after": deal_totals(ad)},
        "changes": {**{k: _top(v, k) for k, v in out_leads.items()},
                    **{f"deals_{k}": v[:SAMPLE] for k, v in out_deals.items()}},
    }


def _status(row: dict | None) -> str:
    if row is None:
        return "not created"
    if row["status"] == "merged":
        return f"merged into {row['merged_into']}" if row.get("merged_into") else "merged"
    return row["status"]


def _named(counts: dict, rep) -> dict:
    return {rep(k) or "Unassigned": v for k, v in counts.items()}


def _top(rows: list[dict], kind: str) -> list[dict]:
    """The most telling changes first: the biggest grade moves, then by name."""
    if kind == "grade":
        rows = sorted(rows, key=lambda r: (-abs(_grade_rank(r["after"]) - _grade_rank(r["before"])),
                                           -abs(r["score_after"] - r["score_before"]), r["name"] or ""))
    return rows[:SAMPLE]


# ================================================================================================ jobs
class WhatIfRuns:
    """What-if runs in background threads, one at a time, polled by id. Only the latest few are kept."""

    def __init__(self):
        self.runs: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def running(self) -> dict | None:
        return next((r for r in self.runs.values() if r["status"] == "running"), None)

    def start(self, *, cfg, active_cfg, overrides: dict, raw: list[dict], historical: list[dict], now: datetime,
              against: dict, label: str, by: str | None, changes: list[dict]) -> dict:
        with self._lock:
            if self.running():
                raise RuntimeError("a what-if run is already in progress")
            rid = next(self._ids)
            run = {"id": rid, "status": "running", "label": label, "created_by": by, "started_at": time.time(),
                   "as_of": iso(now), "events": len(raw), "processed": 0, "passes": 2, "against": against,
                   "overrides": overrides, "settings_changes": changes, "seconds": None, "result": None,
                   "error": None}
            self.runs[rid] = run
            for old in sorted(self.runs)[:-KEEP]:
                self.runs.pop(old)

        def work() -> None:
            try:
                before = replay_under(active_cfg, raw, historical, now, lambda i, n: run.update(processed=i))
                after = replay_under(cfg, raw, historical, now, lambda i, n: run.update(processed=n + i))
                run["result"] = compare(before, after)
                run["status"] = "done"
            except Exception as e:  # noqa: BLE001 - any failure means these rules cannot run
                log.info("what-if run %s failed", rid, exc_info=True)
                run["error"] = f"these settings fail when processing events: {type(e).__name__}: {e}"
                run["status"] = "failed"
            finally:
                run["seconds"] = round(time.time() - run["started_at"], 1)

        threading.Thread(target=work, name=f"whatif-{rid}", daemon=True).start()
        return run


def view(run: dict, detail: bool = True) -> dict:
    out = {k: v for k, v in run.items() if k not in ("result", "overrides", "started_at", "processed", "passes")}
    out["started_at"] = iso(datetime.fromtimestamp(run["started_at"]).astimezone())
    total = run["events"] * run["passes"]
    out["progress"] = 1.0 if run["status"] != "running" or not total else round(run["processed"] / total, 3)
    if detail:
        out["result"] = run["result"]
    return out
