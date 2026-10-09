"""EventBus interface + in-process asyncio implementation.

A Kafka / Redis Streams bus would partition by lead_id; here a single consumer processes events in order,
which trivially preserves per-lead ordering.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Protocol


class EventBus(Protocol):
    async def publish(self, event: dict) -> dict: ...
    def process_now(self, event: dict) -> dict: ...


class AsyncQueueBus:
    def __init__(self, handler: Callable[[dict], dict], lock: asyncio.Lock):
        self._handler = handler
        self._lock = lock
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def publish(self, event: dict) -> dict:
        fut = asyncio.get_running_loop().create_future()
        await self._queue.put((event, fut))
        return await fut

    def process_now(self, event: dict) -> dict:
        """Synchronous path used by the in-process simulator (caller already holds the processing lock)."""
        return self._handler(event)

    async def _consume(self) -> None:
        while True:
            event, fut = await self._queue.get()
            try:
                async with self._lock:
                    result = self._handler(event)
                if not fut.done():
                    fut.set_result(result)
            except Exception as exc:  # surface to the publisher
                if not fut.done():
                    fut.set_exception(exc)
            finally:
                self._queue.task_done()
