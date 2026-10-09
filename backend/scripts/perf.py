"""Performance check: p95 end-to-end processing latency per event at a sustained 50 events/sec.

End-to-end = normalize -> ... -> persist (SQLite commit) for one event, measured around Processor.handle.
Run: python backend/scripts/perf.py   (or: make perf)
"""
from __future__ import annotations

import random
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config  # noqa: E402
from app.engine.types import iso  # noqa: E402
from app.persistence import Persistence  # noqa: E402
from app.runtime import Runtime  # noqa: E402

RATE = 50          # events per second
DURATION_S = 30    # seconds of sustained load


def pct(values, p):
    vs = sorted(values)
    k = (len(vs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)


def main() -> None:
    db_path = Path(__file__).resolve().parents[1] / "var" / "perf.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    rt = Runtime(load_config(), Persistence(f"sqlite:///{db_path}"))
    t0 = time.perf_counter()
    rt.reset()
    print(f"reset (6 months history + 21-day warm-up): {time.perf_counter() - t0:.1f}s, "
          f"{len(rt.store.log)} events, {sum(1 for l in rt.store.leads.values() if rt.store.is_open(l))} open leads")

    rng = random.Random(1)
    open_ids = [lid for lid, l in rt.store.leads.items() if rt.store.is_open(l)]
    kinds = [("page_view", {"page_category": "pricing"}), ("page_view", {"page_category": "blog"}),
             ("email_opened", {}), ("email_clicked", {}), ("content_download", {}), ("demo_request", {}),
             ("email_replied", {"body": "Can you share pricing for 40 seats?"})]
    lat: list[float] = []
    interval = 1.0 / RATE
    n = RATE * DURATION_S
    start = time.perf_counter()
    for i in range(n):
        target = start + i * interval
        while time.perf_counter() < target:
            pass
        kind, payload = rng.choice(kinds)
        if rng.random() < 0.05:
            ev = {"event_id": f"perf_{i:06d}", "type": "lead_created", "source": "website",
                  "payload": {"name": f"Perf Lead{i}", "email": f"perf{i}@acme.io", "company": "Acme", "title": "CTO",
                              "country": "IN", "capture_method": "form_submit", "ip": "103.9.9.9"}}
        else:
            ev = {"event_id": f"perf_{i:06d}", "type": kind, "lead_ref": {"lead_id": rng.choice(open_ids)},
                  "payload": dict(payload)}
        rt.clock.set(rt.clock.now() + timedelta(seconds=1))
        ev["ts"] = iso(rt.clock.now())
        t = time.perf_counter()
        rt.emit(ev)
        lat.append((time.perf_counter() - t) * 1000)
    wall = time.perf_counter() - start
    p95 = pct(lat, 95)
    print(f"sustained load: {n} events in {wall:.1f}s ({n / wall:.1f} events/s target {RATE})")
    print(f"latency ms  p50 {statistics.median(lat):.2f}  p95 {p95:.2f}  p99 {pct(lat, 99):.2f}  max {max(lat):.2f}")
    print(f"tick (rescore all open leads): ", end="")
    t = time.perf_counter()
    rt.processor.handle({"event_id": "perf_tick", "type": "time_tick", "ts": iso(rt.clock.now() + timedelta(hours=1)),
                         "actor": "system"})
    print(f"{(time.perf_counter() - t) * 1000:.0f} ms")
    print("PASS: p95 < 50 ms" if p95 < 50 else "FAIL: p95 >= 50 ms")


if __name__ == "__main__":
    main()
