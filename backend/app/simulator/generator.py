"""Discrete-event simulator: prospect personas, buying committees, duplicates, bots, and reps acting on their queues.

Everything is scheduled on the shared Scheduler with a seeded RNG, so a run is deterministic for a given seed
regardless of the real-time speed multiplier.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from datetime import datetime, timedelta

from ..engine.types import iso
from .personas import bot_identity, ip_for, make_identity, pick, reply_text, variant_identity

DAY = timedelta(days=1)


class Agent:
    __slots__ = ("aid", "persona", "payload", "source", "company", "lead_id", "created_at", "ghosted", "active",
                 "is_member", "alias_of")

    def __init__(self, aid, persona, payload, source, company, created_at, is_member=False, alias_of=None):
        self.aid, self.persona, self.payload, self.source, self.company = aid, persona, payload, source, company
        self.lead_id = None
        self.created_at = created_at
        self.ghosted = False
        self.active = True
        self.is_member = is_member
        self.alias_of = alias_of


class Simulator:
    def __init__(self, cfg, store, scheduler):
        self.cfg = cfg
        self.store = store
        self.scheduler = scheduler
        self.reset(cfg.simulator.seed)

    def reset(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.agents: dict[str, Agent] = {}
        self.by_lead: dict[str, str] = {}
        self.pending: dict[str, str] = {}
        self.seq = 0
        self.background = True
        self.rep_actions = bool(self.cfg.simulator.rep_actions)
        self.suspended = False
        self.companies = sorted(self.cfg.data.companies.values(), key=lambda c: c["domain"])
        self.counts: Counter = Counter()

    # ------------------------------------------------------------------ helpers
    def _eid(self) -> str:
        self.seq += 1
        return f"sim_{self.seq:08d}"

    def _sched(self, ts: datetime, action: str, **data) -> None:
        self.scheduler.schedule(ts, "sim", {"action": action, **data})

    def _ev(self, type_: str, ts: datetime, actor: str = "prospect", lead_id: str | None = None,
            rep_id: str | None = None, source: str | None = None, **payload) -> dict:
        self.counts[type_] += 1
        return {"event_id": self._eid(), "type": type_, "ts": iso(ts), "actor": actor, "rep_id": rep_id,
                "source": source, "lead_ref": {"lead_id": lead_id} if lead_id else {}, "payload": payload}

    def _uniform_hours(self, lo: float, hi: float) -> timedelta:
        return timedelta(hours=self.rng.uniform(lo, hi))

    def _exp_days(self, rate_per_day: float) -> timedelta:
        return timedelta(days=self.rng.expovariate(rate_per_day))

    def _persona(self, name: str):
        return self.cfg.simulator.personas[name]

    def _agent_for(self, lead_id: str | None) -> Agent | None:
        lid = self.store.resolve_lead_id(lead_id)
        aid = self.by_lead.get(lid or "")
        return self.agents.get(aid) if aid else None

    # ------------------------------------------------------------------ bootstrap
    def bootstrap(self, now: datetime) -> None:
        sc = self.cfg.simulator
        self._sched(now + self._exp_days(sc.lead_rate_per_day), "arrival")
        self._sched(now + self._exp_days(sc.bot_bursts_per_week / 7), "bot_burst")

    # ------------------------------------------------------------------ dispatch
    def fire(self, data: dict, now: datetime) -> list[dict]:
        action = data["action"]
        handler = getattr(self, f"_do_{action}")
        return handler(data, now) or []

    def _do_arrival(self, data, now) -> list[dict]:
        sc = self.cfg.simulator
        self._sched(now + self._exp_days(sc.lead_rate_per_day), "arrival")
        if not self.background:
            return []
        source = pick(self.rng, {s: v["share"] for s, v in sc.sources.items()})
        src = sc.sources[source]
        # Purchased lists re-sell people we already know: a duplicate capture.
        if source == "list_vendor_x" and self.agents and self.rng.random() < 0.35:
            known = [a for a in self.agents.values() if a.persona != "bot" and a.lead_id and not a.alias_of]
            if known:
                orig = self.rng.choice(known)
                return [self._capture(variant_identity(self.rng, orig.payload, src["capture"]), source, now,
                                      orig.persona, orig.company, alias_of=orig.aid)]
        persona = pick(self.rng, src["personas"])
        company = self.rng.choice(self.companies)
        free = self.rng.random() < (0.35 if persona == "tire_kicker" else 0.1)
        payload = make_identity(self.rng, self.cfg, company, self._persona(persona).seniority_mix, src["capture"], free)
        return [self._capture(payload, source, now, persona, company)]

    def _capture(self, payload: dict, source: str, now: datetime, persona: str, company: dict | None,
                 alias_of: str | None = None, is_member: bool = False) -> dict:
        aid = f"P{len(self.agents) + 1:05d}"
        agent = Agent(aid, persona, payload, source, company, now, is_member=is_member, alias_of=alias_of)
        self.agents[aid] = agent
        ev = self._ev("lead_created", now, source=source, **payload)
        if source == "webinar":
            ev["payload"]["webinar"] = "Scaling revenue ops"
        self.pending[ev["event_id"]] = aid
        return ev

    def _do_bot_burst(self, data, now) -> list[dict]:
        sc = self.cfg.simulator
        self._sched(now + self._exp_days(sc.bot_bursts_per_week / 7), "bot_burst")
        if not self.background:
            return []
        n = self.rng.randint(*sc.bot_burst_size)
        ip = f"{self.rng.choice(['185', '45', '5', '46'])}.{self.rng.randint(1, 254)}.{self.rng.randint(1, 254)}.7"
        for i in range(n):
            self._sched(now + timedelta(seconds=self.rng.uniform(0, 600)), "bot", ip=ip)
        return []

    def _do_bot(self, data, now) -> list[dict]:
        return [self._capture(bot_identity(self.rng, self.cfg, data["ip"]), "list_vendor_x", now, "bot", None)]

    def _do_agent(self, data, now) -> list[dict]:
        a = self.agents.get(data["aid"])
        if a is None or not a.active or a.ghosted:
            return []
        if a.lead_id is None:
            self._sched(now + timedelta(hours=1), "agent", aid=a.aid)
            return []
        lid = self.store.resolve_lead_id(a.lead_id)
        lead = self.store.leads.get(lid or "")
        if lead is None or lead.stage in ("won", "lost", "disqualified"):
            a.active = False
            return []
        age = (now - a.created_at) / DAY
        phases = self._persona(a.persona).phases
        start = 0.0
        phase = None
        for ph in phases:
            if age < start + ph["days"]:
                phase = ph
                break
            start += ph["days"]
        if phase is None:
            a.active = False
            return []
        phase_end = a.created_at + timedelta(days=start + phase["days"])
        rates = phase["daily"]
        total = sum(rates.values())
        if total <= 0:
            self._sched(phase_end + timedelta(minutes=1), "agent", aid=a.aid)
            return []
        kind = pick(self.rng, rates)
        nxt = now + self._exp_days(total)
        self._sched(min(nxt, phase_end + timedelta(minutes=1)) if nxt > phase_end else nxt, "agent", aid=a.aid)
        return [self._activity(kind, lid, now)]

    def _activity(self, kind: str, lead_id: str, now: datetime) -> dict:
        if kind.startswith("page_"):
            cat = kind[5:]
            return self._ev("page_view", now, lead_id=lead_id, url=f"/{cat.replace('_', '-')}", page_category=cat,
                            session_id=f"s_{self.rng.randint(1, 99999)}")
        if kind == "webinar_registered":
            if self.rng.random() < 0.6:
                self._sched(now + timedelta(days=self.rng.uniform(1, 5)), "react",
                            event=self._ev("webinar_attended", now, lead_id=lead_id, webinar="Product deep dive"),
                            aid=self.by_lead.get(lead_id))
            return self._ev("webinar_registered", now, lead_id=lead_id, webinar="Product deep dive")
        if kind == "content_download":
            return self._ev(kind, now, lead_id=lead_id, asset=self.rng.choice(["pricing-guide.pdf", "roi-calculator.xlsx",
                                                                              "industry-report.pdf", "security-whitepaper.pdf"]))
        return self._ev(kind, now, lead_id=lead_id)

    def _do_react(self, data, now) -> list[dict]:
        a = self.agents.get(data.get("aid") or "")
        if a is not None and a.ghosted and not data.get("force"):
            return []
        ev = dict(data["event"])
        ev["ts"] = iso(now)
        return [ev]

    def _do_resubmit(self, data, now) -> list[dict]:
        orig = self.agents.get(data["aid"])
        if orig is None:
            return []
        sources = sorted(s for s in self.cfg.simulator.sources if s not in (orig.source, "list_vendor_x"))
        source = self.rng.choice(sources)
        cap = self.cfg.simulator.sources[source]["capture"]
        return [self._capture(variant_identity(self.rng, orig.payload, cap), source, now, orig.persona, orig.company,
                              alias_of=orig.aid)]

    def _do_committee(self, data, now) -> list[dict]:
        parent = self.agents.get(data["aid"])
        if parent is None or parent.company is None:
            return []
        src = parent.source
        payload = make_identity(self.rng, self.cfg, parent.company, self._persona("buying_committee").seniority_mix,
                                self.cfg.simulator.sources[src]["capture"])
        return [self._capture(payload, src, now, "buying_committee", parent.company, is_member=True)]

    # ------------------------------------------------------------------ rep behaviour
    def _schedule_rep(self, lead, action: dict, now: datetime) -> None:
        if not self.rep_actions or self.suspended or action["channel"] == "none":
            return
        rep = self.store.reps.get(lead.owner or "")
        if rep is None:
            return
        prof = self.cfg.simulator.rep_profiles[rep["profile"]]
        if self.rng.random() < prof["skip"]:
            return
        lo, hi = prof["delay_minutes"]
        delay = math.exp(self.rng.uniform(math.log(lo), math.log(hi)))
        # Reps work to the action's due time: urgent actions get done after the rep's reaction delay, low-urgency
        # ones ("follow up in 3 days") around their due date.
        due_minutes = (action["due_at"] - now).total_seconds() / 60
        urgent = action["urgency"] in ("critical", "high") or action["rule_id"] == "N12"
        start = 0.0 if urgent else max(0.0, due_minutes * self.rng.uniform(0.6, 1.0) - 60)
        self._sched(now + timedelta(minutes=start + delay), "rep", lead_id=lead.lead_id, action_id=action["id"],
                    rep_id=rep["rep_id"])

    def _do_rep(self, data, now) -> list[dict]:
        lead = self.store.leads.get(data["lead_id"])
        if lead is None or lead.status != "active" or lead.owner != data["rep_id"] or lead.ev is None:
            return []
        act = lead.open_action()
        if act is None or act["id"] != data["action_id"]:
            return []
        rep, lid, stage = data["rep_id"], lead.lead_id, lead.stage
        a = self._agent_for(lid)
        persona = self._persona(a.persona) if a else None
        types = {e.type for e in lead.events}
        acv = round(lead.ev.acv["acv"], -2)
        out: list[dict] = []
        if stage == "negotiation" and "contract_sent" not in types:
            out.append(self._ev("contract_sent", now, "rep", lid, rep, amount=acv))
        elif (stage == "meeting" or act["rule_id"] == "N6") and "proposal_sent" not in types:
            out.append(self._ev("proposal_sent", now, "rep", lid, rep, amount=acv))
        elif act["channel"] == "call":
            connect = persona.respond.connect if persona else 0.5
            ok = not (a and a.ghosted) and self.rng.random() < connect
            outcome = "connected" if ok else self.rng.choice(["voicemail", "no_answer"])
            out.append(self._ev("call_logged", now, "rep", lid, rep, outcome=outcome, template=act["template"]))
            accept = persona.meeting.accept if persona else 0.6
            if ok and stage in ("new", "contacted", "engaged", "qualified", "nurture") and self.rng.random() < accept:
                out.append(self._meeting_scheduled(lid, rep, now))
        elif act["rule_id"] == "N9":
            out.append(self._ev("email_sent", now, "rep", lid, rep, template=act["template"]))
            if self.rng.random() < (persona.meeting.accept if persona else 0.6):
                out.append(self._meeting_scheduled(lid, rep, now))
        elif act["channel"] == "task":
            out.append(self._ev("task_completed", now, "rep", lid, rep, task_type=act["template"]))
        else:
            out.append(self._ev("email_sent", now, "rep", lid, rep, template=act["template"],
                                thread_id=f"t_{lid}"))
        return out

    def _meeting_scheduled(self, lead_id: str, rep: str, now: datetime) -> dict:
        when = now + timedelta(days=self.rng.uniform(1, 4))
        mtype = self.rng.choice(["discovery", "demo"])
        return self._ev("meeting_scheduled", now, "rep", lead_id, rep, meeting_type=mtype, scheduled_for=iso(when))

    def _do_meeting(self, data, now) -> list[dict]:
        lead = self.store.leads.get(self.store.resolve_lead_id(data["lead_id"]) or "")
        if lead is None or lead.stage in ("won", "lost", "disqualified"):
            return []
        a = self._agent_for(lead.lead_id)
        no_show = 1.0 if (a and a.ghosted) else (self._persona(a.persona).meeting.no_show if a else 0.1)
        rep = data.get("rep_id") or lead.owner
        if self.rng.random() < no_show:
            return [self._ev("meeting_no_show", now, "rep", lead.lead_id, rep, meeting_type=data["meeting_type"])]
        return [self._ev("meeting_held", now, "rep", lead.lead_id, rep, meeting_type=data["meeting_type"])]

    def _do_decision(self, data, now) -> list[dict]:
        lead = self.store.leads.get(self.store.resolve_lead_id(data["lead_id"]) or "")
        if lead is None or lead.stage in ("won", "lost", "disqualified") or lead.ev is None:
            return []
        a = self._agent_for(lead.lead_id)
        win = self._persona(a.persona).win_prob if a else 0.5
        rep = lead.owner if lead.owner in self.store.reps else data.get("rep_id")
        if self.rng.random() < min(0.95, win + 0.2):
            return [self._ev("deal_won", now, "rep", lead.lead_id, rep, amount=round(lead.ev.acv["acv"], -2))]
        return [self._ev("deal_lost", now, "rep", lead.lead_id, rep,
                         lost_reason=self.rng.choice(self.cfg.simulator.lost_reasons))]

    def _do_close_ghost(self, data, now) -> list[dict]:
        lead = self.store.leads.get(self.store.resolve_lead_id(data["lead_id"]) or "")
        if lead is None or lead.stage not in ("proposal", "negotiation", "meeting", "qualified"):
            return []
        rep = lead.owner if lead.owner in self.store.reps else None
        return [self._ev("deal_lost", now, "rep", lead.lead_id, rep, lost_reason="no_response")]

    # ------------------------------------------------------------------ processor hooks
    def on_hook(self, kind: str, **data) -> None:
        if kind == "event_processed":
            self._on_processed(data["event"], data["lead"])
        elif kind == "action_created":
            self._schedule_rep(data["lead"], data["action"], data["action"]["ts"])
        elif kind == "assigned":
            lead = data["lead"]
            act = lead.open_action()
            if act and lead.last_eval_at:
                self._schedule_rep(lead, act, lead.last_eval_at)

    def _on_processed(self, e, lead) -> None:
        now = e.ts
        aid = self.pending.pop(e.event_id, None)
        if aid is not None:
            a = self.agents[aid]
            a.lead_id = lead.lead_id
            if a.alias_of is None and lead.lead_id not in self.by_lead:
                self.by_lead[lead.lead_id] = aid
            if a.alias_of is None and a.persona != "bot" and not self.suspended:
                rates = sum(self._persona(a.persona).phases[0]["daily"].values()) or 0.5
                self._sched(now + self._exp_days(rates), "agent", aid=aid)
                p = self._persona(a.persona)
                if a.persona == "duplicate_submitter":
                    lo, hi = p.resubmit_days
                    self._sched(now + timedelta(days=self.rng.uniform(lo, hi)), "resubmit", aid=aid)
                if a.persona == "buying_committee" and not a.is_member:
                    lo, hi = p.committee_size
                    for _ in range(self.rng.randint(lo, hi) - 1):
                        self._sched(now + timedelta(days=self.rng.uniform(0.5, p.committee_spread_days)), "committee",
                                    aid=aid)
            return
        if e.actor != "rep" or self.suspended:
            if e.type == "meeting_scheduled" and not self.suspended:
                self._schedule_meeting(e, lead)
            return
        a = self._agent_for(lead.lead_id)
        if e.type == "meeting_scheduled":
            self._schedule_meeting(e, lead)
        if a is None or a.ghosted:
            return
        p = self._persona(a.persona)
        r = p.respond
        if e.type == "email_sent":
            if self.rng.random() < r.open:
                t_open = now + self._uniform_hours(0.1, 8)
                self._sched(t_open, "react", aid=a.aid, event=self._ev("email_opened", t_open, lead_id=lead.lead_id,
                                                                       thread_id=f"t_{lead.lead_id}"))
                if self.rng.random() < r.click:
                    t_click = t_open + self._uniform_hours(0.02, 2)
                    self._sched(t_click, "react", aid=a.aid,
                                event=self._ev("email_clicked", t_click, lead_id=lead.lead_id,
                                               url=self.rng.choice(["/pricing", "/case-study", "/product"])))
            if self.rng.random() < r.reply:
                t_reply = now + self._uniform_hours(*r.reply_hours)
                if lead.stage in ("proposal", "negotiation"):
                    cls = "negotiation" if self.rng.random() < 0.4 + p.win_prob / 2 else self.rng.choice(["neutral", "objection"])
                else:
                    cls = pick(self.rng, p.reply_mix)
                body = reply_text(self.rng, cls, a.payload.get("seats"))
                self._sched(t_reply, "react", aid=a.aid,
                            event=self._ev("email_replied", t_reply, lead_id=lead.lead_id, body=body,
                                           thread_id=f"t_{lead.lead_id}"))
                if cls == "negative" and self.rng.random() < 0.5:
                    self._sched(t_reply + timedelta(minutes=5), "react", aid=a.aid,
                                event=self._ev("unsubscribed", t_reply, lead_id=lead.lead_id))
        elif e.type == "proposal_sent":
            t_view = now + self._uniform_hours(2, 36)
            self._sched(t_view, "react", aid=a.aid, force=True,
                        event=self._ev("proposal_viewed", t_view, lead_id=lead.lead_id))
            if p.get("ghost_after") == "proposal_sent":
                a.ghosted = True
                prof = self.cfg.simulator.rep_profiles[self.store.reps.get(lead.owner or "", {}).get("profile", "average")]
                self._sched(now + timedelta(days=prof["close_ghosts_after_days"]), "close_ghost", lead_id=lead.lead_id)
            else:
                t_reply = t_view + self._uniform_hours(4, 60)
                cls = "negotiation" if self.rng.random() < 0.45 + p.win_prob / 2 else self.rng.choice(["objection", "neutral"])
                self._sched(t_reply, "react", aid=a.aid,
                            event=self._ev("email_replied", t_reply, lead_id=lead.lead_id,
                                           body=reply_text(self.rng, cls, a.payload.get("seats"))))
        elif e.type == "contract_sent":
            lo, hi = self.cfg.simulator.decision_days
            self._sched(now + timedelta(days=self.rng.uniform(lo, hi)), "decision", lead_id=lead.lead_id,
                        rep_id=e.rep_id)
        elif e.type == "call_logged" and (e.payload or {}).get("outcome") == "connected":
            if self.rng.random() < 0.5:
                t = now + self._uniform_hours(0.5, 6)
                self._sched(t, "react", aid=a.aid, event=self._ev("page_view", t, lead_id=lead.lead_id, url="/pricing",
                                                                  page_category="pricing"))

    def _schedule_meeting(self, e, lead) -> None:
        when = (e.payload or {}).get("scheduled_for")
        from ..engine.types import parse_ts
        ts = parse_ts(when) if when else e.ts + timedelta(days=2)
        self._sched(ts, "meeting", lead_id=lead.lead_id, meeting_type=(e.payload or {}).get("meeting_type", "discovery"),
                    rep_id=e.rep_id)
