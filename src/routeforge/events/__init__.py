"""In-process pub/sub used to publish gateway state changes."""

from .bus import Event, EventBus

__all__ = ["Event", "EventBus"]
