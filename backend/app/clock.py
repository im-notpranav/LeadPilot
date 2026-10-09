"""SimClock: the only source of time. Speed multiplier, pause, step."""
from __future__ import annotations

from datetime import datetime, timedelta

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
