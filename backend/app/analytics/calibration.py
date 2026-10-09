"""Does the score work? Grade vs actual conversion, score distribution, and an optional logistic model
fitted on simulated historical closed deals (coefficients + calibration by decile)."""
from __future__ import annotations

from collections import defaultdict

FEATURES = ["score", "intent_level_index", "stalled", "source_quality", "rep_base_win_rate"]


def score_distribution(store) -> list[dict]:
    bins = defaultdict(int)
    for l in store.leads.values():
        if l.ev is not None and store.is_open(l):
            bins[min(9, int(l.ev.score.score // 10))] += 1
    return [{"bin": f"{b * 10}-{b * 10 + 9}", "count": bins.get(b, 0)} for b in range(10)]


def grade_conversion(store) -> list[dict]:
    hist = defaultdict(lambda: [0, 0])
    for d in store.historical:
        hist[d["grade"]][0] += d["won"]
        hist[d["grade"]][1] += 1
    live = defaultdict(lambda: [0, 0])
    for l in store.leads.values():
        if l.ev is not None and l.stage in ("won", "lost"):
            live[l.ev.score.grade][0] += l.stage == "won"
            live[l.ev.score.grade][1] += 1
    out = []
    for g in "ABCD":
        hw, hn = hist[g]
        lw, ln = live[g]
        out.append({"grade": g, "historical_n": hn, "historical_win_rate": round(hw / hn, 4) if hn else None,
                    "live_n": ln, "live_win_rate": round(lw / ln, 4) if ln else None})
    return out


def train_model(store) -> dict | None:
    cached = getattr(store, "_model", None)
    if cached and cached["n"] == len(store.historical):
        return cached
    if len(store.historical) < 50:
        return None
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:  # optional dependency
        return None
    X = np.array([[float(d["features"][f]) for f in FEATURES] for d in store.historical])
    y = np.array([1 if d["won"] else 0 for d in store.historical])
    model = LogisticRegression(max_iter=1000).fit(X, y)
    p = model.predict_proba(X)[:, 1]
    order = np.argsort(p)
    deciles = []
    for i, chunk in enumerate(np.array_split(order, 10)):
        deciles.append({"decile": i + 1, "predicted": round(float(p[chunk].mean()), 4),
                        "actual": round(float(y[chunk].mean()), 4), "n": int(len(chunk))})
    result = {"n": len(store.historical), "intercept": round(float(model.intercept_[0]), 4),
              "coefficients": [{"feature": f, "coef": round(float(c), 4)} for f, c in zip(FEATURES, model.coef_[0])],
              "calibration": deciles, "base_rate": round(float(y.mean()), 4)}
    store._model = result
    return result


def score_calibration(store) -> dict:
    return {"grades": grade_conversion(store), "score_distribution": score_distribution(store),
            "model": train_model(store)}
