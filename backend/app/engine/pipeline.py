"""Opportunity / pipeline engine: stage as a deterministic fold over the lead's ts-sorted events (pure).

Evidence rules (P1..P11) are applied at each event in timestamp order; time-based rules (P8 negative +
silence, P9 nurture, P10 revive) are applied at checkpoints: before each event (at its ts) and at the final
`now`. Because the fold only depends on the sorted events, any arrival order yields the same stage (I5).
The processor caches the fold state after the last event and only refolds from scratch on late events.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime

from .intent import has_negotiation_terms, reply_class
from .metrics import is_inbound
from .profile import PROFILE_EVENT_TYPES, apply_profile_event
from .scoring import compute_score
from .types import Event, LeadContext, Profile, ScoreResult, Transition, age_days

QUAL_SIGNALS = ("demo_request", "contact_sales", "bant_qualified")


@dataclass
class FoldState:
    profile: Profile = field(default_factory=Profile)
    stage: str = "new"
    stage_entered_at: datetime | None = None
    pre_disq_stage: str | None = None
    disq_reason: str | None = None
    negative_reply_at: datetime | None = None
    negative_reply_id: str | None = None
    proposal_sent_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_inbound_id: str | None = None
    last_qual_signal_at: datetime | None = None
    last_qual_signal_id: str | None = None
    last_key: tuple | None = None
    n_events: int = 0

    def copy(self) -> "FoldState":
        s = FoldState(**{f.name: getattr(self, f.name) for f in fields(self)})
        s.profile = self.profile.copy()
        return s


def _label(rule: str, cfg) -> str:
    return cfg.pipeline.rule_labels.get(rule, rule)


def _set(s: FoldState, to: str, rule: str, evidence: list, ts, trans: list, cfg, mode: str = "auto",
         reason: str | None = None, trigger: str | None = None) -> None:
    if to == s.stage:
        return
    trans.append(Transition(ts=ts, from_stage=s.stage, to_stage=to, rule_id=rule, evidence=list(evidence), mode=mode,
                            reason=reason or _label(rule, cfg), trigger_event_id=trigger))
    s.stage = to
    s.stage_entered_at = ts


def _advance(s: FoldState, target: str, rule: str, evidence: list, ts, trans: list, cfg, trigger=None) -> None:
    """Forward-only move; a single event may skip stages, each intermediate step is recorded with the same evidence."""
    rank = cfg.derived.forward_rank
    order = cfg.pipeline.forward_order
    if s.stage == "nurture":
        _set(s, target, rule, evidence, ts, trans, cfg, trigger=trigger)
        return
    if s.stage not in rank or rank[target] <= rank[s.stage]:
        return
    for r in range(rank[s.stage] + 1, rank[target] + 1):
        _set(s, order[r], rule, evidence, ts, trans, cfg, trigger=trigger)


def _p3_ok(s: FoldState, sc: ScoreResult, ts, cfg) -> bool:
    r = cfg.pipeline.rules.P3_qualify
    if sc.fit < r.min_fit or s.profile.fake_status == "fake":
        return False
    recent_signal = s.last_qual_signal_at is not None and age_days(ts, s.last_qual_signal_at) <= r.signal_window_days
    return sc.intent >= r.min_intent or recent_signal


def _time_rules(s: FoldState, t, events_before: list[Event], ctx: LeadContext, cfg, trans: list, trigger_id,
                score: ScoreResult | None = None, allow_revive: bool = False) -> ScoreResult | None:
    """Time-based transitions evaluated at checkpoint time t."""
    if s.stage in cfg.derived.terminal:
        return score
    rules = cfg.pipeline.rules
    trig = [trigger_id] if trigger_id else []
    # P8: negative reply followed by N days with no inbound
    if (s.negative_reply_at is not None and s.last_inbound_at is not None
            and s.last_inbound_at <= s.negative_reply_at
            and age_days(t, s.negative_reply_at) >= rules.P8_lost_after_negative_days):
        _set(s, "lost", "P8", [s.negative_reply_id] + trig, t, trans, cfg,
             reason=f"Negative reply and {rules.P8_lost_after_negative_days}d without inbound", trigger=trigger_id)
        return score
    # P9: early-stage, low score, long silence -> nurture
    p9 = rules.P9_nurture
    rank = cfg.derived.forward_rank
    ref = s.last_inbound_at or s.profile.created_at
    if (s.stage in rank and rank[s.stage] <= rank[p9.max_stage] and ref is not None
            and age_days(t, ref) >= p9.inactive_days):
        if score is None:
            score = compute_score(s.profile, events_before, t, ctx, cfg)
        if score.score < p9.max_score:
            ev = [s.last_inbound_id or s.profile.created_event_id] + trig
            _set(s, "nurture", "P9", [e for e in ev if e], t, trans, cfg,
                 reason=f"No inbound for {int(age_days(t, ref))}d and score {score.score:.1f} < {p9.max_score}",
                 trigger=trigger_id)
            return score
    # P10: revive from nurture when the score recovers
    if allow_revive and s.stage == "nurture":
        if score is None:
            score = compute_score(s.profile, events_before, t, ctx, cfg)
        if score.score >= rules.P10_revive_score:
            ev = [s.last_inbound_id] + trig if s.last_inbound_id else trig
            _set(s, "engaged", "P10", ev or trig, t, trans, cfg,
                 reason=f"Score recovered to {score.score:.0f} (>= {rules.P10_revive_score})", trigger=trigger_id)
    return score


def fold_step(state: FoldState, e: Event, events_upto: list[Event], ctx: LeadContext, cfg) -> tuple[FoldState, list]:
    """Apply one event. `events_upto` is the lead's sorted history up to and including e."""
    s = state.copy()
    trans: list[Transition] = []
    rank = cfg.derived.forward_rank

    # 1. time rules at the event's timestamp, before the event is applied
    if s.n_events > 0 and s.stage not in cfg.derived.terminal:
        _time_rules(s, e.ts, events_upto[:-1], ctx, cfg, trans, e.event_id)

    # 2. bookkeeping
    if e.type in PROFILE_EVENT_TYPES:
        apply_profile_event(s.profile, e, cfg)
    if s.stage_entered_at is None:
        s.stage_entered_at = e.ts
    if is_inbound(e, cfg):
        s.last_inbound_at, s.last_inbound_id = e.ts, e.event_id
    if e.type in QUAL_SIGNALS:
        s.last_qual_signal_at, s.last_qual_signal_id = e.ts, e.event_id
    reply_cls = None
    if e.type == "email_replied":
        reply_cls = reply_class(e.payload, cfg)
        if reply_cls == "negative":
            s.negative_reply_at, s.negative_reply_id = e.ts, e.event_id
        elif reply_cls in ("positive_intent", "neutral", "objection"):
            s.negative_reply_at = s.negative_reply_id = None
    if e.type == "proposal_sent":
        s.proposal_sent_at = e.ts

    # 3. event-driven rules
    _event_rules(s, e, reply_cls, events_upto, ctx, cfg, trans, rank)
    s.last_key = e.sort_key
    s.n_events += 1
    return s, trans


def _event_rules(s: FoldState, e: Event, reply_cls, events_upto, ctx, cfg, trans, rank) -> None:
    t = e.type
    pl = e.payload or {}
    ev = [e.event_id]

    # Manual and quality transitions (always allowed)
    if t == "stage_override":
        to = pl.get("to_stage")
        if to in cfg.pipeline.stages and to != s.stage:
            if to == "disqualified":
                s.pre_disq_stage, s.disq_reason = s.stage, "manual"
            _set(s, to, "M1", ev, e.ts, trans, cfg, mode="manual", reason=pl.get("reason") or "Manual override",
                 trigger=e.event_id)
        return
    if t == "lead_disqualified":
        if s.stage != "disqualified":
            s.pre_disq_stage, s.disq_reason = s.stage, "manual"
            _set(s, "disqualified", "P11", ev, e.ts, trans, cfg, mode="manual",
                 reason=pl.get("reason") or "Disqualified by rep", trigger=e.event_id)
        return
    if t == "quality_cleared":
        if s.stage == "disqualified" and s.disq_reason == "fake":
            _set(s, s.pre_disq_stage or "new", "Q1", ev, e.ts, trans, cfg, mode="manual",
                 reason="Quality flag marked false positive", trigger=e.event_id)
            s.disq_reason = None
        return
    if t == "quality_assessed":
        if pl.get("status") == "fake" and s.stage != "disqualified" and not s.profile.quality_reviewed:
            s.pre_disq_stage, s.disq_reason = s.stage, "fake"
            _set(s, "disqualified", "P11", ev, e.ts, trans, cfg,
                 reason=f"Quarantined as fake (fake score {pl.get('fake_score')})", trigger=e.event_id)
        return
    if s.stage in cfg.derived.terminal:
        return
    if t == "deal_lost":
        _set(s, "lost", "P8", ev, e.ts, trans, cfg, reason=f"Deal lost: {pl.get('lost_reason', 'unspecified')}",
             trigger=e.event_id)
        return

    targets: list[tuple[str, str]] = []
    if e.actor == "rep" and t in cfg.derived.rep_outbound_types:
        targets.append(("contacted", "P1"))
    if t == "email_replied" and reply_cls in ("positive_intent", "neutral", "objection"):
        targets.append(("engaged", "P2"))
        if (reply_cls == "positive_intent" and s.proposal_sent_at is not None
                and has_negotiation_terms(pl.get("body"), cfg)):
            targets.append(("negotiation", "P6"))
    if t == "call_logged" and pl.get("outcome") == "connected":
        targets.append(("engaged", "P2"))
    if t == "meeting_scheduled":
        targets.append(("engaged", "P2"))
    if t == "meeting_held" and pl.get("meeting_type", "discovery") in cfg.pipeline.rules.P4_meeting_types:
        targets.append(("meeting", "P4"))
    if t == "proposal_sent":
        targets.append(("proposal", "P5"))
    if t == "contract_sent":
        targets.append(("negotiation", "P6"))
    if t == "deal_won":
        targets.append(("won", "P7"))

    if s.stage == "nurture":
        targets = [x for x in targets if rank[x[0]] >= rank["engaged"]]
    if targets:
        best = max(targets, key=lambda x: rank[x[0]])
        _advance(s, best[0], best[1], ev, e.ts, trans, cfg, trigger=e.event_id)

    # Score-based rules (P10 revive, P3 qualify) need the score at this event
    needs_score = s.stage == "nurture" or (s.stage in rank and rank[s.stage] < rank["qualified"])
    if needs_score and not e.derived or (needs_score and t == "lead_enriched"):
        sc = compute_score(s.profile, events_upto, e.ts, ctx, cfg)
        if s.stage == "nurture" and sc.score >= cfg.pipeline.rules.P10_revive_score:
            _set(s, "engaged", "P10", ev, e.ts, trans, cfg,
                 reason=f"Score recovered to {sc.score:.0f} (>= {cfg.pipeline.rules.P10_revive_score})",
                 trigger=e.event_id)
        if (s.stage == "nurture" or rank.get(s.stage, 99) < rank["qualified"]) and _p3_ok(s, sc, e.ts, cfg):
            evidence = ev + ([s.last_qual_signal_id] if s.last_qual_signal_id and s.last_qual_signal_id != e.event_id else [])
            r = cfg.pipeline.rules.P3_qualify
            why = (f"Fit {sc.fit:.0f} >= {r.min_fit} and "
                   + (f"intent {sc.intent:.0f} >= {r.min_intent}" if sc.intent >= r.min_intent
                      else "recent demo/contact/BANT signal"))
            _advance(s, "qualified", "P3", evidence, e.ts, trans, cfg, trigger=e.event_id)
            for tr in trans:
                if tr.rule_id == "P3":
                    tr.reason = why


def checkpoint(state: FoldState, events: list[Event], now, ctx: LeadContext, cfg,
               trigger_id: str | None) -> tuple[FoldState, list, ScoreResult]:
    """Apply time rules at `now` on a copy of the cached fold state. Returns (state, transitions, score at now)."""
    score = compute_score(state.profile, events, now, ctx, cfg)
    if state.n_events == 0 or not _time_rules_may_fire(state, now, cfg):
        return state, [], score          # read-only use by callers; no copy needed
    s = state.copy()
    trans: list[Transition] = []
    _time_rules(s, now, events, ctx, cfg, trans, trigger_id, score=score, allow_revive=True)
    return s, trans, score


def _time_rules_may_fire(s: FoldState, t, cfg) -> bool:
    if s.stage in cfg.derived.terminal:
        return False
    if s.stage == "nurture" or s.negative_reply_at is not None:
        return True
    rules = cfg.pipeline.rules
    rank = cfg.derived.forward_rank
    ref = s.last_inbound_at or s.profile.created_at
    return (s.stage in rank and rank[s.stage] <= rank[rules.P9_nurture.max_stage] and ref is not None
            and age_days(t, ref) >= rules.P9_nurture.inactive_days)


def run_fold(events: list[Event], ctx: LeadContext, cfg, lead_id: str | None = None) -> tuple[FoldState, list]:
    """Fold from scratch over sorted events. Returns (state after last event, all transitions)."""
    s = FoldState(profile=Profile(lead_id=lead_id))
    all_trans: list[Transition] = []
    for i, e in enumerate(events):
        s, tr = fold_step(s, e, events[: i + 1], ctx, cfg)
        all_trans.extend(tr)
    return s, all_trans
