"""Full lead evaluation at time `now` (pure): stage checkpoint, score, metrics, stall, prediction, NBA."""
from __future__ import annotations

from dataclasses import dataclass, field

from .enrich import segment_for
from .metrics import engagement_metrics
from .nba import recommend
from .pipeline import FoldState, checkpoint
from .prediction import close_probability, predict_acv
from .stall import detect_stall
from .types import Event, LeadContext, Profile, ScoreResult, age_days


@dataclass
class Evaluation:
    profile: Profile
    score: ScoreResult
    stage: str
    stage_entered_at: object
    days_in_stage: float
    transitions: list
    metrics: dict
    stall: dict
    acv: dict
    close: dict
    expected_value: float
    nba: list = field(default_factory=list)
    segment: str | None = None


def evaluate(fold: FoldState, events: list[Event], now, ctx: LeadContext, cfg,
             trigger_id: str | None = None) -> Evaluation:
    final, trans, score = checkpoint(fold, events, now, ctx, cfg, trigger_id)
    metrics = engagement_metrics(events, now, cfg)
    days_in_stage = age_days(now, final.stage_entered_at) if final.stage_entered_at else 0.0
    stall = detect_stall(final.stage, metrics, events, now, ctx, cfg)
    acv = predict_acv(final.profile, events, cfg)
    close = close_probability(final.stage, score, stall, ctx, cfg)
    nba = recommend(final.stage, final.profile, score, metrics, stall, events, now, cfg)
    return Evaluation(profile=final.profile, score=score, stage=final.stage, stage_entered_at=final.stage_entered_at,
                      days_in_stage=days_in_stage, transitions=trans, metrics=metrics, stall=stall, acv=acv,
                      close=close, expected_value=acv["acv"] * close["p"], nba=nba,
                      segment=segment_for(final.profile.employees, cfg))
