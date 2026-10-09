"""Clocks: the only sources of time. SimClock (demo: speed, pause, step) and WallClock (live: real UTC)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .engine.types import iso, parse_ts


class SimClock:
    def __init__(self, start: datetime | str, speed: float = 60.0, paused: bool = True):
        self._now = parse_ts(start)
        self.speed = float(speed)
        self.paused = paused

    def now(self) -> datetime:
        return self._now

    def set(self, t: datetime) -> None:
        if t > self._now:
            self._now = t

    def reset(self, t: datetime | str) -> None:
        self._now = parse_ts(t)

    def target_after(self, real_seconds: float) -> datetime:
        return self._now + timedelta(seconds=real_seconds * self.speed)

    def step_target(self, n_minutes: float) -> datetime:
        return self._now + timedelta(minutes=n_minutes)

    def state(self) -> dict:
        return {"now": iso(self._now), "speed": self.speed, "paused": self.paused}


class WallClock:
    """Live mode: real UTC time. Same interface as SimClock; it cannot be paused, sped up or moved."""

    live = True
    speed = 1.0
    paused = False

    def now(self) -> datetime:
        # Whole seconds: the raw log stores ingested_at at this precision, so replay sees the same "now".
        return datetime.now(timezone.utc).replace(microsecond=0)

    def set(self, t: datetime) -> None: ...

    def reset(self, t: datetime | str | None = None) -> None: ...

    def target_after(self, real_seconds: float) -> datetime:
        return self.now()

    def step_target(self, n_minutes: float) -> datetime:
        return self.now()

    def state(self) -> dict:
        return {"now": iso(self.now()), "speed": 1.0, "paused": False, "live": True}
