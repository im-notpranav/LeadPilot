"""The processing pipeline (one call per event, per-lead ordered):

 1 Normalize -> 2 Identity/Dedupe -> 3 Quality (fake) -> 4 Enrich -> 5 Append to event store
 6 Recompute LeadState (score, intent, stage, stall, deal prediction) -> 7 Assignment / Reassignment
 8 Next-best-action -> 9 Priority -> 10 Persist projections + derived records -> 11 Broadcast

All decision logic lives in app.engine (pure functions); this module only wires state, I/O and time.
"""
from __future__ import annotations

import bisect
import time
from datetime import datetime, timedelta

from .analytics.source_quality import compute_source_quality
from .engine.assignment import check_reassignment, choose_rep, first_touch_deadline, lead_facts
from .engine.enrich import MockEnrichmentProvider, enrich
from .engine.evaluate import evaluate
from .engine.explain import diff, merge_contribution, summary
from .engine.identity import blocking_keys, identity_of, resolve
from .engine.normalize import normalize_capture
from .engine.pipeline import FoldState, fold_step, run_fold
from .engine.prediction import close_probability
from .engine.priority import compute_priority
from .engine.quality import assess
from .engine.types import Event, LeadContext, Profile, Transition, iso, parse_ts
from .persistence import NullPersistence
from .store import LeadRecord, Store

EVENT_TYPES = {
    "lead_created", "page_view", "content_download", "webinar_registered", "webinar_attended", "demo_request",
    "contact_sales", "trial_signup", "proposal_viewed", "email_sent", "email_opened", "email_clicked",
    "email_replied", "email_bounced", "unsubscribed", "call_logged", "meeting_scheduled", "meeting_held",
    "meeting_no_show", "proposal_sent", "contract_sent", "deal_won", "deal_lost", "task_created", "task_completed",
    "stage_override", "lead_disqualified", "bant_qualified", "time_tick",
    # manual / system extensions
    "manual_assign", "quality_cleared", "merge_approved", "review_rejected", "sla_check", "lead_refresh",
    # derived (written by the processor)
    "quality_assessed", "lead_enriched", "lead_merged",
}
GLOBAL_TYPES = {"time_tick", "sla_check", "merge_approved", "review_rejected"}
MATCH_DESC = {"email_norm": "same email", "phone_e164": "same phone", "domain": "same domain + name",
              "company_norm": "same company + name"}


class Processor:
    def __init__(self, cfg, store: Store, clock=None, persistence=None, provider=None):
        self.cfg = cfg
        self.store = store
        self.clock = clock
        self.db = persistence or NullPersistence()
        self.provider = provider or MockEnrichmentProvider(cfg)
        self.hooks: list = []            # callables(kind, **data): simulator + scheduler integration
        self.outbox: list[dict] = []     # websocket messages
        self.broadcast = True
        self.hooks_enabled = True
        self.autoflush = True
        self._api_seq = 0
        self._replaying = False
        self._importing = False

    # ================================================================ public
    def handle(self, raw: dict | Event) -> dict:
        t0 = time.perf_counter()
        raw_dict = raw.to_dict() if isinstance(raw, Event) else dict(raw)
        e = self._to_event(raw_dict)
        if e.event_id in self.store.events:
            return {"status": "duplicate", "event_id": e.event_id}
        if e.type not in EVENT_TYPES:
            return {"status": "rejected", "event_id": e.event_id, "reason": f"unknown event type {e.type}"}
        ingested = parse_ts(raw_dict["ingested_at"]) if raw_dict.get("ingested_at") else (
            self.clock.now() if self.clock else e.ts)
        now = max(e.ts, ingested)
        raw_dict["event_id"], raw_dict["ts"], raw_dict["ingested_at"] = e.event_id, iso(e.ts), iso(ingested)
        if not self._replaying:
            self.store.raw_log.append(raw_dict)
            self.db.add("raw_events", {"seq": len(self.store.raw_log), "event_id": e.event_id, "body": raw_dict})
        # A history import (past activity loaded as-of its own time) never triggers live SLA reassignment.
        self._importing = bool(raw_dict.get("import"))
        self._store_event(e, ingested)

        result: dict = {"status": "processed", "event_id": e.event_id, "type": e.type}
        if e.type == "time_tick":
            result.update(self._tick(e, now))
        elif e.type == "sla_check":
            result.update(self._sla_check(e, now))
        elif e.type == "merge_approved":
            result.update(self._merge_approved(e, now))
        elif e.type == "review_rejected":
            result.update(self._review_rejected(e, now))
        elif e.type == "lead_created":
            lead = self._capture(e, now)
            result.update(self._finish(lead, e, now))
        else:
            lead = self._resolve(e)
            if lead is None:
                self.store.unresolved.append(e.event_id)
                result["status"] = "unresolved"
            else:
                e.lead_id = lead.lead_id
                self._persist_event(e)
                if e.type == "lead_refresh":
                    self._evaluate_and_record(lead, now, e, [], force_row=True)
                else:
                    self._apply(lead, e, now)
                if e.type == "manual_assign":
                    rep = (e.payload or {}).get("rep_id")
                    if rep in self.store.reps:
                        self._set_owner(lead, rep, now, "manual", (e.payload or {}).get("reason")
                                        or f"Manually assigned to {self.store.rep_name(rep)}", [], rule=None)
                elif e.type == "quality_cleared":
                    if lead.status == "quarantined":
                        lead.status = "active"
                    reviewer = (e.payload or {}).get("reviewed_by", "manager")
                    if lead.quality:
                        lead.quality.update(status="clean (reviewed)", reviewed_by=reviewer)
                        self.db.upsert("quality_flags", {"lead_id": lead.lead_id, **lead.quality, "ts": now})
                    self._resolve_review((e.payload or {}).get("review_id"), "approved", now)
                elif e.type == "lead_disqualified":
                    self._resolve_review((e.payload or {}).get("review_id"), "disqualified", now)
                result.update(self._finish(lead, e, now))
        if self.autoflush:
            self.db.flush()
        if e.type not in ("time_tick",):
            self.store.latencies.append((time.perf_counter() - t0) * 1000)
        return result

    def replay(self, write: bool = True) -> dict:
        """Rebuild every projection from the raw event log (same code path as live processing).

        write=False rebuilds memory only: used on restart when the stored projections were produced by this
        same config, so rewriting them would change nothing.
        """
        raw = [dict(r) for r in self.store.raw_log]
        self.store.reset_projections()
        db = self.db
        if write:
            db.clear_projections()
            db.clear_events()
        else:
            self.db = NullPersistence()
        hooks, bc, af = self.hooks_enabled, self.broadcast, self.autoflush
        self.hooks_enabled, self.broadcast, self.autoflush = False, False, False
        self._replaying = True
        try:
            for i, r in enumerate(raw):
                self.handle(r)
                if i % 500 == 0:
                    self.db.flush()
            self.db.flush()
        finally:
            self._replaying = False
            self.hooks_enabled, self.broadcast, self.autoflush = hooks, bc, af
            self.db = db
        if write:
            db.set_meta("projection_config", self.cfg.fingerprint)
            db.flush()
        self.store.raw_log = raw
        return {"replayed_events": len(raw), "leads": len(self.store.leads), "rewrote_projections": write}

    def restore_api_seq(self) -> None:
        """Continue generated `api_` ids after the highest one in the raw log, so a restart never reuses one."""
        nums = [int(r["event_id"][4:]) for r in self.store.raw_log
                if str(r.get("event_id", "")).startswith("api_") and r["event_id"][4:].isdigit()]
        self._api_seq = max(nums, default=0)

    # ================================================================ step 1: normalize the envelope
    def _to_event(self, d: dict) -> Event:
        eid = d.get("event_id")
        if not eid:
            self._api_seq += 1
            eid = f"api_{self._api_seq:07d}"
        ts = parse_ts(d["ts"]) if d.get("ts") else (self.clock.now() if self.clock else datetime.now().astimezone())
        actor = d.get("actor") or ("system" if d.get("type") in GLOBAL_TYPES else "prospect")
        return Event(event_id=eid, type=d.get("type", ""), ts=ts, actor=actor, rep_id=d.get("rep_id"),
                     source=d.get("source"), payload=dict(d.get("payload") or {}),
                     lead_ref=dict(d.get("lead_ref") or {}), lead_id=None, derived=bool(d.get("derived", False)))

    def _store_event(self, e: Event, ingested: datetime) -> None:
        e.seq = self.store.next_id("seq")
        self.store.events[e.event_id] = e
        self.store.log.append(e)
        self.store.ingested_at[e.event_id] = ingested
        self._persist_event(e)

    def _persist_event(self, e: Event) -> None:
        """Upsert: the last write in a step wins, so lead_id resolved later in the step is persisted."""
        self.db.upsert("events", {"event_id": e.event_id, "seq": e.seq, "lead_id": e.lead_id, "type": e.type,
                                  "ts": e.ts, "actor": e.actor, "rep_id": e.rep_id, "source": e.source,
                                  "payload": e.payload, "lead_ref": e.lead_ref, "derived": e.derived,
                                  "ingested_at": self.store.ingested_at.get(e.event_id)})

    def _resolve(self, e: Event) -> LeadRecord | None:
        ref = e.lead_ref or {}
        lid = self.store.resolve_lead_id(ref.get("lead_id"))
        if lid:
            return self.store.leads[lid]
        if ref.get("email") or ref.get("phone"):
            ident = normalize_capture({"email": ref.get("email"), "phone": ref.get("phone"),
                                       "country": ref.get("country")}, self.cfg)
            for key in blocking_keys(ident):
                if key[0] in ("email", "phone"):
                    for cand in sorted(self.store.block_index.get(key, ())):
                        lid = self.store.resolve_lead_id(cand)
                        if lid:
                            return self.store.leads[lid]
        return None

    # ================================================================ steps 2-5: capture
    def _capture(self, e: Event, now: datetime) -> LeadRecord:
        cfg, store = self.cfg, self.store
        pl = e.payload
        ident = normalize_capture(pl, cfg)
        cands: dict[str, dict] = {}
        for key in blocking_keys(ident):
            for lid in store.block_index.get(key, ()):
                rid = store.resolve_lead_id(lid)
                if rid and store.leads[rid].profile is not None and rid not in cands:
                    cands[rid] = identity_of(store.leads[rid].profile)
        res = resolve(ident, list(cands.items()), cfg)
        ip_count = store.ip_hit(pl.get("ip"), e.ts)

        if res.action == "merge":
            survivor = store.leads[res.lead_id]
            dup_id = store.new_lead_id()
            dup = LeadRecord(dup_id, source=e.source, created_at=e.ts, status="merged",
                             merged_into=survivor.lead_id, is_duplicate_capture=True)
            store.leads[dup_id] = dup
            desc = " / ".join(MATCH_DESC.get(k.split("=")[0], k) for k in res.match_keys if "=" not in k) or "match"
            desc = f"{desc} via {e.source}"
            e.lead_id = survivor.lead_id
            e.payload = {**pl, "merged_from": dup_id, "match": {"confidence": res.confidence, "keys": res.match_keys}}
            merge = {"id": store.next_id("merge"), "survivor_id": survivor.lead_id, "merged_id": dup_id,
                     "confidence": res.confidence, "match_keys": res.match_keys, "ts": now, "mode": "auto",
                     "source": e.source}
            store.merges.append(merge)
            self.db.add("merges", merge)
            self.db.upsert("leads", {"lead_id": dup_id, "status": "merged", "merged_into": survivor.lead_id,
                                     "source_primary": e.source, "created_at": e.ts, "name": ident.get("name"),
                                     "email_norm": ident.get("email_norm")})
            self._persist_event(e)
            self._emit("lead.merged", {"survivor_id": survivor.lead_id, "merged_id": dup_id,
                                       "confidence": res.confidence, "mode": "auto", "reason": desc})
            self._apply(survivor, e, now, merge_info=(dup_id, desc))
            for key in blocking_keys(ident):
                store.block_index[key].add(survivor.lead_id)
            return survivor

        lead = LeadRecord(store.new_lead_id(), source=e.source, created_at=e.ts)
        store.leads[lead.lead_id] = lead
        e.lead_id = lead.lead_id
        self._persist_event(e)
        self._apply(lead, e, now)
        for key in blocking_keys(ident):
            store.block_index[key].add(lead.lead_id)

        # 3. quality
        domain = ident.get("email_domain")
        q = assess(ident, pl, {"ip_submissions_last_hour": ip_count, "mx_valid": self.provider.mx_valid(domain),
                               "ip_country": self.provider.ip_country(pl.get("ip")),
                               "disposable": self.provider.is_disposable(domain)}, cfg)
        qe = Event(f"{e.event_id}.1q", "quality_assessed", e.ts, actor="system", source=e.source, payload=q,
                   lead_id=lead.lead_id, derived=True)
        self._store_event(qe, now)
        self._apply(lead, qe, now)
        lead.quality = {"fake_score": q["fake_score"], "signals": q["signals"], "status": q["status"],
                        "reviewed_by": None, "ts": iso(now)}
        self.db.upsert("quality_flags", {"lead_id": lead.lead_id, **lead.quality, "ts": now})
        if q["status"] == "fake":
            lead.status = "quarantined"
            self._emit("lead.flagged", {"lead_id": lead.lead_id, "status": "fake", "fake_score": q["fake_score"],
                                        "signals": [s["key"] for s in q["signals"]], "source": e.source})
        elif q["status"] == "suspicious":
            self._add_review("suspicious", lead.lead_id, None, q["fake_score"] / 100, [],
                             {"signals": q["signals"]}, now)
            self._emit("lead.flagged", {"lead_id": lead.lead_id, "status": "suspicious",
                                        "fake_score": q["fake_score"], "source": e.source})

        # 4. enrichment
        enr = enrich(ident, self.provider, cfg)
        if enr:
            ee = Event(f"{e.event_id}.2e", "lead_enriched", e.ts, actor="system", source=e.source, payload=enr,
                       lead_id=lead.lead_id, derived=True)
            self._store_event(ee, now)
            self._apply(lead, ee, now)
            if enr.get("found"):
                self.db.upsert("accounts", {"company_id": enr["account_id"], "normalized_name": ident.get("company_norm"),
                                            "domain": enr["domain"], "employees": enr["employees"],
                                            "employee_band": enr["employee_band"], "industry": enr["industry"],
                                            "revenue_band": enr["revenue_band"], "country": enr["hq_country"],
                                            "region": ident.get("region"), "tech_stack": enr["tech_stack"],
                                            "funding_stage": enr["funding_stage"]})
        candidate = store.leads.get(res.lead_id or "")
        if res.action == "review" and lead.status != "quarantined" and candidate is not None \
                and candidate.status != "quarantined":
            self._add_review("duplicate", lead.lead_id, res.lead_id, res.confidence, res.match_keys, {}, now)
        return lead

    # ================================================================ step 6: recompute
    def _context(self, lead: LeadRecord) -> LeadContext:
        store = self.store
        p = lead.profile
        activity = []
        if p is not None and p.account_id:
            for lid in store.account_index.get(p.account_id, ()):
                if lid == lead.lead_id:
                    continue
                other = store.leads[lid]
                if other.status == "merged":
                    continue
                activity.extend((x.ts, lid) for x in other.events if x.actor == "prospect" and not x.derived)
        source = (p.source_primary if p else None) or lead.source
        sq = store.source_stats.get(source or "", {})
        return LeadContext(account_activity=activity, expired_actions=list(lead.expired_action_ts),
                           rep_segment_win_rate=store.rep_segment_win_rate(lead.owner, store.segment_of(lead))
                           if lead.owner else None,
                           team_win_rate=store.team_win_rate,
                           source_quality_index=sq.get("quality_index", self.cfg.quality.source_quality.default_index),
                           owner_rep_id=lead.owner)

    def _apply(self, lead: LeadRecord, e: Event, now: datetime, merge_info: tuple | None = None,
               force_refold: bool = False) -> dict:
        keys = [x.sort_key for x in lead.events]
        idx = bisect.bisect_right(keys, e.sort_key)
        lead.events.insert(idx, e)
        ctx = self._context(lead)
        in_order = lead.fold is not None and lead.fold.last_key is not None and e.sort_key > lead.fold.last_key
        if lead.fold is None and len(lead.events) == 1:
            lead.fold, trans = fold_step(FoldState(profile=Profile(lead_id=lead.lead_id)), e, lead.events, ctx, self.cfg)
        elif in_order and not force_refold:
            lead.fold, trans = fold_step(lead.fold, e, lead.events, ctx, self.cfg)
        else:
            lead.fold, trans = run_fold(lead.events, ctx, self.cfg, lead_id=lead.lead_id)
        p = lead.profile
        if p.account_id and lead.lead_id not in self.store.account_index[p.account_id]:
            self.store.account_index[p.account_id].add(lead.lead_id)
        return self._evaluate_and_record(lead, now, e, trans, merge_info=merge_info, force_row=True)

    def _evaluate_and_record(self, lead: LeadRecord, now: datetime, trigger: Event, fold_trans: list,
                             merge_info: tuple | None = None, force_row: bool = True) -> dict:
        cfg, store = self.cfg, self.store
        ctx = self._context(lead)
        ev = evaluate(lead.fold, lead.events, now, ctx, cfg, trigger_id=trigger.event_id if trigger else None)
        old, new = lead.last_stored_score, ev.score.score
        stage_changed = ev.stage != lead.stage
        stall_changed = ev.stall["is_stalled"] != lead.is_stalled
        row = None
        if force_row or abs(new - old) >= cfg.scoring.store_threshold or stage_changed or stall_changed:
            contribs = diff(lead.last_factors, ev.score.factors, cfg)
            if merge_info:
                contribs = merge_contribution(contribs, merge_info[0], merge_info[1])
            text = summary(old, new, contribs, trigger.type if trigger else None, ev.score.factors)
            row = {"id": store.next_id("score_change"), "lead_id": lead.lead_id,
                   "event_id": trigger.event_id if trigger else None, "event_type": trigger.type if trigger else None,
                   "ts": now, "old_score": old, "new_score": new, "delta": new - old, "contributions": contribs,
                   "summary": text, "grade": ev.score.grade, "intent_level": ev.score.intent_level,
                   "parts": ev.score.parts()}
            lead.score_history.append(row)
            self.db.add("score_changes", row)
            self.db.add("factor_snapshots", {"id": row["id"], "lead_id": lead.lead_id, "event_id": row["event_id"],
                                             "ts": now, "factors": {k: f.to_dict() for k, f in ev.score.factors.items()},
                                             "parts": ev.score.parts()})
            lead.last_factors = ev.score.factors
            lead.last_stored_score = new
            if abs(new - old) >= 0.05 or (trigger and trigger.type != "time_tick"):
                self._emit("score.changed", {"lead_id": lead.lead_id, "old": round(old, 2), "new": round(new, 2),
                                             "delta": round(new - old, 2), "summary": text,
                                             "event_type": row["event_type"]})
        self._log_transitions(lead, list(fold_trans) + list(ev.transitions), ev.stage, trigger, now)
        self._stall_flags(lead, ev, trigger, now)
        lead.ev = ev
        lead.stage = ev.stage
        lead.last_eval_at = now
        if ev.stage in ("won", "lost") and not lead.outcome_counted and lead.owner:
            lead.outcome_counted = True
            store.record_outcome(lead.owner, ev.segment, ev.stage == "won", ev.acv["acv"] if ev.stage == "won" else 0)
        return row or {}

    def _log_transitions(self, lead: LeadRecord, cands: list[Transition], new_stage: str, trigger: Event | None,
                         now: datetime) -> None:
        old = lead.stage
        if old == new_stage:
            return
        chain: list[Transition] = []
        target = new_stage
        for t in reversed(cands):
            if t.to_stage == target:
                chain.append(t)
                target = t.from_stage
                if target == old:
                    break
        if target != old or not chain:
            last = next((t for t in reversed(cands) if t.to_stage == new_stage), None)
            chain = [Transition(ts=now, from_stage=old, to_stage=new_stage, rule_id=last.rule_id if last else "SYNC",
                                evidence=(last.evidence if last else [trigger.event_id] if trigger else []),
                                mode=last.mode if last else "auto",
                                reason=(last.reason if last else "Recomputed from history"))]
        else:
            chain.reverse()
        for t in chain:
            row = {"id": self.store.next_id("transition"), "lead_id": lead.lead_id, "ts": t.ts if t.ts else now,
                   "from_stage": t.from_stage, "to_stage": t.to_stage, "rule_id": t.rule_id,
                   "evidence_event_ids": [x for x in t.evidence if x], "mode": t.mode, "reason": t.reason}
            if not row["evidence_event_ids"] and trigger is not None:
                row["evidence_event_ids"] = [trigger.event_id]
            lead.transitions.append(row)
            self.db.add("stage_transitions", row)
            self._emit("stage.changed", {"lead_id": lead.lead_id, "from": t.from_stage, "to": t.to_stage,
                                         "rule_id": t.rule_id, "reason": t.reason, "mode": t.mode})

    def _stall_flags(self, lead: LeadRecord, ev, trigger: Event | None, now: datetime) -> None:
        stalled = ev.stall["is_stalled"]
        if stalled and not lead.is_stalled:
            flag = {"id": self.store.next_id("stall"), "lead_id": lead.lead_id, "ts_detected": now,
                    "rule_ids": ev.stall["rules"], "details": ev.stall["details"], "risk": ev.stall["risk"],
                    "cleared_at": None, "cleared_by_event_id": None}
            lead.open_stall = flag
            lead.stall_flags.append(flag)
            self.db.add("stall_flags", flag)
            self._emit("stall.detected", {"lead_id": lead.lead_id, "rules": ev.stall["rules"],
                                          "details": ev.stall["details"], "risk": ev.stall["risk"]})
        elif not stalled and lead.is_stalled:
            flag = lead.open_stall
            if flag:
                flag["cleared_at"] = now
                flag["cleared_by_event_id"] = trigger.event_id if trigger else None
                self.db.add("stall_flags", {**flag, "id": self.store.next_id("stall")})
            lead.open_stall = None
            self._emit("stall.cleared", {"lead_id": lead.lead_id,
                                         "cleared_by_event_id": trigger.event_id if trigger else None})
        elif stalled and lead.open_stall:
            lead.open_stall.update(rule_ids=ev.stall["rules"], details=ev.stall["details"], risk=ev.stall["risk"])
        lead.is_stalled = stalled

    # ================================================================ steps 7-11
    def _finish(self, lead: LeadRecord, e: Event, now: datetime) -> dict:
        if lead.status != "merged":
            if lead.owner is None:
                self._maybe_assign(lead, now)
            elif not self._importing:
                self._check_reassign(lead, now)
            self._actions(lead, now, e)
            self._priority(lead, now)
            self._persist_lead(lead)
        ev = lead.ev
        p = lead.profile
        rows = [r for r in lead.score_history[-4:] if r["event_id"] and r["event_id"].startswith(e.event_id)]
        delta = sum(r["delta"] for r in rows)
        text = rows[-1]["summary"] if rows else ""
        if e.type == "lead_created" and ev is not None and not (e.payload or {}).get("merged_from"):
            text = (f"New lead via {e.source}: score {ev.score.score:.0f} ({ev.score.grade}), "
                    f"fit {ev.score.fit:.0f}, intent {ev.score.intent_level}"
                    + (f", quarantined (fake {p.fake_score:.0f})" if p.fake_status == "fake" else ""))
        item = {"ts": iso(now), "event_id": e.event_id, "type": e.type, "lead_id": lead.lead_id,
                "name": p.name if p else None, "company": p.company if p else None, "actor": e.actor,
                "rep_id": e.rep_id, "source": e.source, "delta": round(delta, 2),
                "score": round(ev.score.score, 1) if ev else None, "grade": ev.score.grade if ev else None,
                "stage": ev.stage if ev else None, "summary": text}
        self.store.feed.appendleft(item)
        self._emit("event.processed", item)
        self._hook("event_processed", event=e, lead=lead)
        return {"lead_id": lead.lead_id, "score": item["score"], "delta": item["delta"], "stage": item["stage"],
                "summary": item["summary"]}

    def _maybe_assign(self, lead: LeadRecord, now: datetime) -> None:
        if lead.owner or lead.status != "active" or lead.stage in self.cfg.derived.terminal or lead.ev is None:
            return
        self._assign_best(lead, now, "initial")

    def _assign_best(self, lead: LeadRecord, now: datetime, kind: str, exclude: tuple = (), rule: str | None = None,
                     prefix: str = "") -> None:
        store = self.store
        ev = lead.ev
        facts = lead_facts(lead.profile, ev.score.grade, ev.score.intent_level, self.cfg)
        stats = {}
        for rid in store.reps:
            st = store.rep_stats[rid]
            stats[rid] = {"load": store.rep_load(rid), "last_assigned_at": st["last_assigned_at"],
                          "wins": st["wins"], "closed": st["closed"]}
        reps = [r for r in store.reps.values() if r.get("active", True)]
        res = choose_rep(facts, reps, stats, store.team_win_rate, self.cfg, exclude=exclude)
        if res["rep_id"]:
            self._set_owner(lead, res["rep_id"], now, kind, prefix + res["reason"], res["candidates"], rule=rule)

    def _set_owner(self, lead: LeadRecord, rep_id: str, now: datetime, kind: str, reason: str, candidates: list,
                   rule: str | None) -> None:
        store = self.store
        prev = lead.owner
        store.set_owner_index(lead, rep_id)
        lead.owner = rep_id
        lead.assigned_at = now
        if rep_id in store.rep_stats:
            store.rep_stats[rep_id]["last_assigned_at"] = now
            store.rep_stats[rep_id]["assigned"] += 1
        cand_view = [{k: (iso(v) if isinstance(v, datetime) else v) for k, v in c.items()} for c in candidates]
        row = {"id": store.next_id("assignment"), "lead_id": lead.lead_id, "rep_id": rep_id, "ts": now,
               "reason": reason, "candidate_scores": cand_view, "type": kind, "previous_rep_id": prev,
               "rule_id": rule}
        lead.assignments.append(row)
        self.db.add("assignments", row)
        m = lead.ev.metrics if lead.ev else {}
        touched = m.get("last_outbound_at") is not None and m["last_outbound_at"] >= now
        mgr = self.cfg.assignment.reassignment.manager_queue_id
        if rep_id != mgr and not touched and lead.ev is not None:
            lead.first_touch_deadline = first_touch_deadline(now, lead.ev.score.grade, self.cfg)
            self._hook("sla_deadline", lead_id=lead.lead_id, deadline=lead.first_touch_deadline)
        else:
            lead.first_touch_deadline = None
        act = lead.open_action()
        if act:
            act["rep_id"] = rep_id
            self.db.upsert("actions", self._action_row(act))
        if lead.ev is not None:  # owner changed: refresh the rep-dependent close probability
            ev = lead.ev
            ev.close = close_probability(ev.stage, ev.score, ev.stall, self._context(lead), self.cfg)
            ev.expected_value = ev.acv["acv"] * ev.close["p"]
        self._emit("lead.reassigned" if prev else "lead.assigned",
                   {"lead_id": lead.lead_id, "rep_id": rep_id, "rep_name": store.rep_name(rep_id),
                    "previous_rep_id": prev, "reason": reason, "type": kind, "rule_id": rule})
        self._hook("assigned", lead=lead, rep_id=rep_id)

    def _check_reassign(self, lead: LeadRecord, now: datetime) -> None:
        if lead.status != "active" or lead.ev is None:
            return
        m = lead.ev.metrics
        if lead.first_touch_deadline and m.get("last_outbound_at") and lead.assigned_at and \
                m["last_outbound_at"] >= lead.assigned_at:
            lead.first_touch_deadline = None
        info = {"owner": lead.owner, "assigned_at": lead.assigned_at, "stage": lead.ev.stage,
                "grade": lead.ev.score.grade, "last_outbound_at": m.get("last_outbound_at"),
                "last_rep_activity_at": m.get("last_rep_activity_at"), "stage_entered_at": lead.ev.stage_entered_at}
        r = check_reassignment(info, now, self.cfg)
        if not r:
            return
        prev = lead.owner
        st = self.store.rep_stats.get(prev)
        if st:
            st["neglect_count"] += 1
            st["reassigned_away"] += 1
        rc = self.cfg.assignment.reassignment
        if lead.auto_reassign_count >= rc.max_auto_reassignments:
            self._set_owner(lead, rc.manager_queue_id, now, "escalation",
                            f"R3: escalated to manager queue after {lead.auto_reassign_count} auto-reassignments "
                            f"({r['rule']}: {r['reason']})", [], rule="R3")
        else:
            lead.auto_reassign_count += 1
            self._assign_best(lead, now, "reassign", exclude=(prev,), rule=r["rule"],
                              prefix=f"{r['rule']}: {r['reason']}. Re")

    def _actions(self, lead: LeadRecord, now: datetime, trigger: Event | None) -> None:
        ev = lead.ev
        act = lead.open_action()
        if act and trigger is not None and trigger.actor == "rep" and \
                trigger.type in self.cfg.derived.rep_activity_types and trigger.ts >= act["ts"]:
            self._close_action(act, "done", now, trigger.event_id)
            act = None
        primary = ev.nba[0] if ev and ev.nba else None
        if primary is None:
            if act:
                self._close_action(act, "superseded", now, None)
            return
        if act and act["rule_id"] == primary["rule_id"]:
            act["reason"] = primary["reason"]
            act["alternates"] = ev.nba[1:]
            return
        if act:
            self._close_action(act, "superseded", now, None)
        new = {"id": f"A-{self.store.next_id('action')}", "lead_id": lead.lead_id, "rep_id": lead.owner, "ts": now,
               "rule_id": primary["rule_id"], "action": primary["action"], "channel": primary["channel"],
               "due_at": now + timedelta(minutes=primary["due_minutes"]), "urgency": primary["urgency"],
               "reason": primary["reason"], "template": primary["template"], "status": "open",
               "completion": primary["completion"], "alternates": ev.nba[1:], "closed_at": None,
               "closed_by_event_id": None}
        lead.actions.append(new)
        self.db.upsert("actions", self._action_row(new))
        self._emit("action.recommended", {"lead_id": lead.lead_id, "rule_id": new["rule_id"], "action": new["action"],
                                          "due_at": iso(new["due_at"]), "rep_id": lead.owner, "reason": new["reason"]})
        self._hook("action_created", lead=lead, action=new)

    def _close_action(self, act: dict, status: str, now: datetime, event_id: str | None) -> None:
        act["status"] = status
        act["closed_at"] = now
        act["closed_by_event_id"] = event_id
        self.db.upsert("actions", self._action_row(act))

    @staticmethod
    def _action_row(a: dict) -> dict:
        return {k: a.get(k) for k in ("id", "lead_id", "rep_id", "ts", "rule_id", "action", "channel", "due_at",
                                       "urgency", "reason", "template", "status", "closed_at", "closed_by_event_id")}

    def _priority(self, lead: LeadRecord, now: datetime) -> None:
        ev = lead.ev
        if ev is None or not self.store.is_open(lead):
            lead.priority, lead.priority_drivers = 0.0, []
            return
        act = lead.open_action()
        due_in = (act["due_at"] - now).total_seconds() / 60 if act else None
        label = act["reason"] if act else None
        sla_left = (lead.first_touch_deadline - now).total_seconds() / 60 if lead.first_touch_deadline else None
        r = compute_priority(ev.score.score, ev.expected_value, self.store.p95_ev, due_in, label,
                             ev.stall["risk"], ev.stage, sla_left, self.cfg)
        lead.priority, lead.priority_drivers = r["priority"], r["drivers"]

    def _persist_lead(self, lead: LeadRecord) -> None:
        if not self.db.enabled:
            return
        ev, p = lead.ev, lead.profile
        if ev is None:
            return
        m = ev.metrics
        self.db.upsert("leads", {
            "lead_id": lead.lead_id, "account_id": p.account_id, "name": p.name, "email_norm": p.email_norm,
            "phone_e164": p.phone_e164, "title": p.title, "seniority": p.seniority, "company": p.company,
            "source_primary": p.source_primary, "sources": p.sources, "status": lead.status,
            "merged_into": lead.merged_into, "owner_rep_id": lead.owner, "stage": ev.stage,
            "is_stalled": ev.stall["is_stalled"], "score": ev.score.score, "grade": ev.score.grade,
            "intent_level": ev.score.intent_level, "fake_score": p.fake_score, "predicted_acv": ev.acv["acv"],
            "close_prob": ev.close["p"], "expected_value": ev.expected_value, "priority": lead.priority,
            "created_at": p.created_at, "last_inbound_at": m["last_inbound_at"],
            "last_outbound_at": m["last_outbound_at"], "first_response_at": m["first_response_at"]})

    # ================================================================ system events
    def _tick(self, e: Event, now: datetime) -> dict:
        store = self.store
        rescored = 0
        open_leads = [l for l in store.leads.values() if l.fold is not None and l.status != "merged"
                      and l.stage not in self.cfg.derived.terminal]
        grace = timedelta(hours=self.cfg.nba.expire_grace_hours)
        for lead in open_leads:
            for a in lead.actions:
                if a["status"] == "open" and now > a["due_at"] + grace:
                    self._close_action(a, "expired", now, e.event_id)
                    lead.expired_action_ts.append(now)
            row = self._evaluate_and_record(lead, now, e, [], force_row=False)
            if row:
                rescored += 1
            if lead.owner is None:
                self._maybe_assign(lead, now)
            else:
                self._check_reassign(lead, now)
            self._actions(lead, now, None)
        evs = [l.ev.expected_value for l in open_leads if l.ev is not None and l.status == "active"]
        store.p95_ev = max(1.0, store.percentile(evs, self.cfg.nba.priority.ev_percentile))
        for lead in open_leads:
            self._priority(lead, now)
            self._persist_lead(lead)
        self._source_quality(now)
        store.last_tick_at = now
        return {"rescored": rescored, "open_leads": len(open_leads)}

    def _source_quality(self, now: datetime) -> None:
        store = self.store
        stats = compute_source_quality(store, self.cfg, now, window_days=30)
        for sid, s in stats.items():
            prev = store.source_flags.get(sid, [])
            if s["flagged"] and not prev:
                self._emit("source.flagged", {"source_id": sid, "reasons": s["flag_reasons"]})
            store.source_flags[sid] = s["flag_reasons"] if s["flagged"] else []
        store.source_stats = stats
        day = now.strftime("%Y-%m-%d")
        if store.last_snapshot_day != day:
            store.last_snapshot_day = day
            for sid, s in stats.items():
                row = {"id": store.next_id("sq_daily"), "source_id": sid, "date": day,
                       **{k: s.get(k) for k in ("volume", "dup_rate", "fake_rate", "contact_rate", "sql_rate", "win_rate",
                                                "median_first_response_min", "avg_score", "revenue", "quality_index",
                                                "flagged", "flag_reasons")}}
                store.source_daily.append(row)
                self.db.add("source_quality_daily", row)

    def refresh_source_quality(self, now: datetime) -> None:
        self._source_quality(now)

    def _sla_check(self, e: Event, now: datetime) -> dict:
        lid = self.store.resolve_lead_id((e.payload or {}).get("lead_id"))
        if not lid:
            return {"checked": None}
        lead = self.store.leads[lid]
        before = lead.owner
        if lead.ev is not None and lead.status == "active":
            self._evaluate_and_record(lead, now, e, [], force_row=False)
            self._check_reassign(lead, now)
            if lead.owner != before:
                self._actions(lead, now, None)
                self._priority(lead, now)
                self._persist_lead(lead)
        return {"checked": lid, "reassigned": lead.owner != before, "lead_id": lid}

    def _add_review(self, kind: str, lead_id: str, candidate: str | None, conf: float, keys: list, detail: dict,
                    now: datetime) -> None:
        rid = f"RV-{self.store.next_id('review')}"
        item = {"id": rid, "kind": kind, "lead_id": lead_id, "candidate_id": candidate, "confidence": conf,
                "match_keys": keys, "detail": detail, "status": "open", "ts": now, "resolved_at": None,
                "resolution": None}
        self.store.review[rid] = item
        self.db.upsert("review_queue", item)

    def _merge_approved(self, e: Event, now: datetime) -> dict:
        store = self.store
        pl = e.payload or {}
        a, b = store.resolve_lead_id(pl.get("lead_id")), store.resolve_lead_id(pl.get("candidate_id"))
        if not a or not b or a == b:
            return {"status": "noop"}
        order = sorted([a, b], key=lambda x: int(x.split("-")[1]))
        survivor, merged = store.leads[order[0]], store.leads[order[1]]
        moved = list(merged.events)
        for x in moved:
            x.lead_id = survivor.lead_id
        self.db.repoint_events([x.event_id for x in moved], survivor.lead_id)
        survivor.events = sorted(survivor.events + moved, key=lambda x: x.sort_key)
        merged.events = []
        store.set_owner_index(merged, None)
        merged.status, merged.merged_into, merged.owner = "merged", survivor.lead_id, None
        for act in merged.actions:
            if act["status"] == "open":
                self._close_action(act, "superseded", now, e.event_id)
        conf = pl.get("confidence", 0.0)
        me = Event(f"{e.event_id}.m", "lead_merged", now, actor="system",
                   payload={"merged_id": merged.lead_id, "confidence": conf, "match_keys": pl.get("match_keys", [])},
                   lead_id=survivor.lead_id, derived=True)
        self._store_event(me, now)
        self._apply(survivor, me, now, merge_info=(merged.lead_id, "approved in review"), force_refold=True)
        merge = {"id": store.next_id("merge"), "survivor_id": survivor.lead_id, "merged_id": merged.lead_id,
                 "confidence": conf, "match_keys": pl.get("match_keys", []), "ts": now, "mode": "review",
                 "source": merged.source}
        store.merges.append(merge)
        self.db.add("merges", merge)
        self._resolve_review(pl.get("review_id"), "merged", now)
        self.db.upsert("leads", {"lead_id": merged.lead_id, "status": "merged", "merged_into": survivor.lead_id})
        self._emit("lead.merged", {"survivor_id": survivor.lead_id, "merged_id": merged.lead_id, "confidence": conf,
                                   "mode": "review"})
        self._finish(survivor, me, now)
        return {"status": "merged", "survivor_id": survivor.lead_id, "merged_id": merged.lead_id}

    def _review_rejected(self, e: Event, now: datetime) -> dict:
        self._resolve_review((e.payload or {}).get("review_id"), "rejected", now)
        return {"status": "rejected"}

    def _resolve_review(self, rid: str | None, resolution: str, now: datetime) -> None:
        item = self.store.review.get(rid or "")
        if item:
            item.update(status="resolved", resolution=resolution, resolved_at=now)
            self.db.upsert("review_queue", item)

    # ================================================================ plumbing
    def _emit(self, kind: str, data: dict) -> None:
        if self.broadcast:
            self.outbox.append({"type": kind, "data": data})

    def _hook(self, kind: str, **data) -> None:
        if self.hooks_enabled:
            for h in self.hooks:
                h(kind, **data)

    def drain_outbox(self) -> list[dict]:
        out, self.outbox = self.outbox, []
        return out
