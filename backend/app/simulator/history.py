"""Six months of historical closed deals, generated at reset (win rates, calibration, optional model)."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

SEGMENT_ACV = {"smb": 8000, "mid_market": 35000, "enterprise": 90000}
GRADE_SCORE = [("A", 80, 100), ("B", 60, 80), ("C", 40, 60), ("D", 10, 40)]


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def generate_history(cfg, rng: random.Random, start: datetime) -> list[dict]:
    sc = cfg.simulator
    sources = sorted(sc.sources)
    industries = ["saas", "fintech", "healthcare_it", "ecommerce", "logistics", "manufacturing", "retail", "education"]
    deals = []
    n = 0
    for rep in cfg.data.reps:
        base = _logit(rep["base_win_rate"])
        for month in range(sc.history_months):
            for _ in range(sc.history_deals_per_rep_month):
                n += 1
                closed = start - timedelta(days=30 * month + rng.uniform(0, 30))
                created = closed - timedelta(days=rng.uniform(10, 75))
                seg = rng.choice(rep["segments"])
                grade, lo, hi = rng.choices(GRADE_SCORE, weights=[0.18, 0.3, 0.3, 0.22])[0]
                score = rng.uniform(lo, hi)
                intent_idx = min(4, max(0, int(round((score - 20) / 20 + rng.uniform(-1, 1)))))
                source = rng.choice(sources)
                src_q = 0.25 if source == "list_vendor_x" else rng.uniform(0.45, 0.8)
                stalled = rng.random() < 0.25
                z = base + 0.045 * (score - 50) + 0.25 * (intent_idx - 2) - 0.7 * stalled + 0.8 * (src_q - 0.5)
                won = rng.random() < 1 / (1 + math.exp(-z))
                amount = SEGMENT_ACV[seg] * rng.uniform(0.6, 1.5)
                deals.append({
                    "id": f"H-{n:05d}", "rep_id": rep["rep_id"], "source": source, "segment": seg,
                    "industry": rng.choice(rep["industries"] if rng.random() < 0.7 else industries),
                    "created_at": created, "closed_at": closed, "won": won, "amount": round(amount, 2),
                    "score": round(score, 1), "grade": grade,
                    "features": {"score": round(score, 1), "intent_level_index": intent_idx, "stalled": stalled,
                                 "source_quality": round(src_q, 3), "rep_base_win_rate": rep["base_win_rate"]},
                })
    return deals
