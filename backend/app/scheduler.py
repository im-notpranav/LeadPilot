"""Scheduler: a deterministic time-ordered queue of future work.

Holds time_tick emissions (decay, stall checks, SLA breaches, reassignment), first-touch SLA checks, and the
simulator's scheduled prospect/rep behaviour. Items fire in (ts, seq) order, so a run is deterministic
regardless of wall-clock speed.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(order=True)
class Item:
    ts: datetime
    seq: int
    kind: str = field(compare=False)
    data: Any = field(compare=False, default=None)


class Scheduler:
    def __init__(self):
        self._heap: list[Item] = []
        self._seq = 0

    def clear(self) -> None:
        self._heap.clear()
        self._seq = 0

    def schedule(self, ts: datetime, kind: str, data: Any = None) -> None:
        self._seq += 1
        heapq.heappush(self._heap, Item(ts, self._seq, kind, data))

    def peek_ts(self) -> datetime | None:
        return self._heap[0].ts if self._heap else None

    def pop(self) -> Item:
        return heapq.heappop(self._heap)

    def __len__(self) -> int:
        return len(self._heap)

    def pending(self, kind: str | None = None) -> int:
        return sum(1 for i in self._heap if kind is None or i.kind == kind)
