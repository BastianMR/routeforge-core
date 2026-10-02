"""In-process pub/sub bus with a replay ring buffer.

Fire-and-forget: `publish` never blocks on a subscriber. A subscriber that
falls behind its queue has the event dropped and `dropped` is incremented.
"""

from __future__ import annotations

import asyncio
import itertools
import os
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_BUFFER_SIZE = 100
SUBSCRIBER_QUEUE_SIZE = 256

# Event type constants. Kept as plain strings so they serialize straight into
# the SSE `event:` field and the MCP notification payload.
COOLDOWN_STARTED = "account.cooldown_started"
RECOVERED = "account.recovered"
DISABLED = "account.disabled"
SKILL_RELOADED = "skill.reloaded"
USAGE_TICK = "usage.tick"
CALL_COMPLETED = "call.completed"


def default_buffer_size() -> int:
    """Ring buffer size, overridable via `ROUTE_FORGE_EVENT_BUFFER_SIZE`."""
    raw = os.environ.get("ROUTE_FORGE_EVENT_BUFFER_SIZE")
    if not raw:
        return DEFAULT_BUFFER_SIZE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_BUFFER_SIZE
    return value if value > 0 else DEFAULT_BUFFER_SIZE


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    id: int
    ts: str

    def to_sse(self) -> str:
        """Render as an SSE frame."""
        import json

        return (
            f"event: {self.type}\n"
            f"id: {self.id}\n"
            f"data: {json.dumps(self.data)}\n\n"
        )


class Subscription:
    """A single subscriber's view of the bus."""

    def __init__(self, bus: EventBus, queue: asyncio.Queue[Event]) -> None:
        self._bus = bus
        self._queue = queue
        self.dropped = 0

    async def get(self) -> Event:
        return await self._queue.get()

    def try_get(self) -> Event | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def replay_after(self, last_event_id: int) -> list[Event]:
        """Buffered events newer than `last_event_id`, oldest first."""
        return self._bus.replay_after(last_event_id)

    def close(self) -> None:
        self._bus.unsubscribe(self)


class EventBus:
    def __init__(self, buffer_size: int | None = None) -> None:
        self._buffer: deque[Event] = deque(maxlen=buffer_size or default_buffer_size())
        self._subscribers: list[Subscription] = []
        self._ids = itertools.count(1)
        self.published = 0
        self.dropped = 0

    def emit(self, event_type: str, **data: Any) -> Event:
        """Publish an event. Alias kept short because call sites are dense."""
        stamp = datetime.now(UTC).isoformat()
        payload = {"ts": stamp, **data}
        return self.publish(Event(type=event_type, data=payload, id=self._next_id(), ts=stamp))

    def _next_id(self) -> int:
        return next(self._ids)

    def publish(self, event: Event) -> Event:
        self.published += 1
        self._buffer.append(event)
        for sub in list(self._subscribers):
            try:
                sub._queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.dropped += 1
                self.dropped += 1
        return event

    def subscribe(self, maxsize: int = SUBSCRIBER_QUEUE_SIZE) -> Subscription:
        sub = Subscription(self, asyncio.Queue(maxsize=maxsize))
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self._subscribers:
            self._subscribers.remove(sub)

    def replay_after(self, last_event_id: int) -> list[Event]:
        return [e for e in self._buffer if e.id > last_event_id]

    def recent(self, limit: int | None = None) -> list[Event]:
        """Buffered events, newest last."""
        events = list(self._buffer)
        if limit is not None:
            return events[-limit:]
        return events

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
