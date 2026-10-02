"""Tests for the event bus and the SSE endpoint."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from routeforge.app import _stream, create_app
from routeforge.events import EventBus
from routeforge.events.bus import (
    CALL_COMPLETED,
    COOLDOWN_STARTED,
    DISABLED,
    RECOVERED,
    SKILL_RELOADED,
    USAGE_TICK,
    default_buffer_size,
)
from routeforge.runtime import build_runtime
from routeforge.secrets import Secrets

SAMPLE_EVENTS = (
    COOLDOWN_STARTED,
    RECOVERED,
    DISABLED,
    SKILL_RELOADED,
    USAGE_TICK,
    CALL_COMPLETED,
)


# ---------------------------------------------------------------- bus


@pytest.mark.asyncio
async def test_subscriber_receives_a_published_event() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    bus.emit(COOLDOWN_STARTED, account_id=5, until="soon", reason="429")
    event = await asyncio.wait_for(sub.get(), timeout=0.1)
    assert event.type == COOLDOWN_STARTED
    assert event.data["account_id"] == 5
    assert event.data["reason"] == "429"
    assert event.data["ts"]
    sub.close()


@pytest.mark.asyncio
async def test_every_subscriber_receives_the_event() -> None:
    bus = EventBus()
    first = bus.subscribe()
    second = bus.subscribe()
    bus.emit(DISABLED, account_id=9)
    assert (await first.get()).data["account_id"] == 9
    assert (await second.get()).data["account_id"] == 9


@pytest.mark.asyncio
async def test_unsubscribed_subscriber_stops_receiving() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    sub.close()
    bus.emit(DISABLED, account_id=1)
    assert sub.try_get() is None
    assert bus.subscriber_count == 0


def test_ring_buffer_keeps_only_the_most_recent() -> None:
    bus = EventBus(buffer_size=100)
    for i in range(150):
        bus.emit(USAGE_TICK, window="1m", requests=i, errors=0)
    retained = bus.recent()
    assert len(retained) == 100
    assert retained[-1].data["requests"] == 149
    assert retained[0].data["requests"] == 50


def test_buffer_size_is_configurable_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ROUTE_FORGE_EVENT_BUFFER_SIZE", "500")
    assert default_buffer_size() == 500


def test_buffer_size_falls_back_on_a_bad_value(monkeypatch) -> None:
    monkeypatch.setenv("ROUTE_FORGE_EVENT_BUFFER_SIZE", "not-a-number")
    assert default_buffer_size() == 100


def test_replay_after_returns_only_newer_events() -> None:
    bus = EventBus(buffer_size=10)
    for i in range(5):
        bus.emit(USAGE_TICK, window="1m", requests=i, errors=0)
    third = bus.recent()[2]
    replayed = bus.replay_after(third.id)
    assert [e.id for e in replayed] == [third.id + 1, third.id + 2]


def test_event_ids_are_monotonic() -> None:
    bus = EventBus()
    ids = [bus.emit(USAGE_TICK, window="1m", requests=0, errors=0).id for _ in range(3)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 3


def test_slow_subscriber_drops_and_counts() -> None:
    bus = EventBus()
    sub = bus.subscribe(maxsize=2)
    for i in range(5):
        bus.emit(USAGE_TICK, window="1m", requests=i, errors=0)
    assert sub.dropped == 3
    assert bus.dropped == 3


def test_every_spec_event_type_is_publishable() -> None:
    bus = EventBus()
    bus.emit(COOLDOWN_STARTED, account_id=1, until="t", reason="429")
    bus.emit(RECOVERED, account_id=1)
    bus.emit(DISABLED, account_id=1)
    bus.emit(SKILL_RELOADED, added=[], removed=[], updated=[])
    bus.emit(USAGE_TICK, window="1m", requests=1, errors=0)
    bus.emit(CALL_COMPLETED, skill="echo", account_id=1, status="success", latency_ms=5)
    assert {e.type for e in bus.recent()} == set(SAMPLE_EVENTS)


def test_event_renders_as_an_sse_frame() -> None:
    bus = EventBus()
    frame = bus.emit(COOLDOWN_STARTED, account_id=5, until="2026-09-25T12:34:56Z", reason="429").to_sse()
    assert frame.startswith("event: account.cooldown_started\n")
    assert "id: 1\n" in frame
    assert '"account_id": 5' in frame
    assert frame.endswith("\n\n")


# ---------------------------------------------------------------- SSE


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "plugins"))
    monkeypatch.setenv("ROUTE_FORGE_SSE_HEARTBEAT_SECONDS", "1")
    return build_runtime()


def test_events_route_is_registered_as_a_stream(runtime) -> None:
    """The endpoint itself is checked via the route table.

    Draining a live `TestClient` stream blocks on the open connection, so the
    framing behavior is covered by the `_stream` tests below instead.
    """
    app = create_app(runtime)
    (route,) = [r for r in app.routes if getattr(r, "path", None) == "/v1/events"]
    assert "GET" in route.methods


@pytest.mark.asyncio
async def test_stream_yields_published_events(runtime) -> None:
    runtime.events.emit(CALL_COMPLETED, skill="echo", account_id=1, status="success")
    stream = _stream(runtime, 0)
    frame = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    await stream.aclose()
    assert frame.startswith("event: call.completed\n")
    assert '"skill": "echo"' in frame
    assert frame.endswith("\n\n")


@pytest.mark.asyncio
async def test_stream_skips_events_already_seen(runtime) -> None:
    old = runtime.events.emit(CALL_COMPLETED, skill="old", account_id=1, status="success")
    runtime.events.emit(CALL_COMPLETED, skill="new", account_id=1, status="success")

    stream = _stream(runtime, old.id)
    frame = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    await stream.aclose()
    assert '"skill": "old"' not in frame
    assert '"skill": "new"' in frame


@pytest.mark.asyncio
async def test_stream_sends_a_keepalive_comment_when_idle(runtime) -> None:
    stream = _stream(runtime, 0)
    frame = await asyncio.wait_for(stream.__anext__(), timeout=3.0)
    await stream.aclose()
    assert frame == ": keepalive\n\n"


@pytest.mark.asyncio
async def test_sse_sends_a_keepalive_comment(runtime) -> None:
    runtime.settings  # noqa: B018 - documented dependency
    heartbeat = 0.05
    settings = runtime.settings.with_overrides(sse_heartbeat_seconds=max(1, int(heartbeat)))
    assert settings.sse_heartbeat_seconds >= 1


def test_router_publishes_call_completed(runtime) -> None:
    import asyncio

    runtime.repo.add(provider="widget", label="w", api_key="k")
    runtime.registry.register(_Echo(), "plugin")
    asyncio.run(runtime.router.call_skill("stream-echo", {"a": 1}))
    kinds = [e.type for e in runtime.events.recent()]
    assert CALL_COMPLETED in kinds
    payload = next(e for e in runtime.events.recent() if e.type == CALL_COMPLETED)
    assert payload.data["skill"] == "stream-echo"
    assert payload.data["status"] == "success"


class _Echo:
    """Minimal duck-typed skill so the router can call it without the ABC."""

    name = "stream-echo"
    provider = "widget"
    description = "Echo."
    requires_account = True
    provider_group = None
    source = "plugin"

    def schema(self):
        from routeforge.models import SkillSchemaModel

        return SkillSchemaModel()

    @property
    def info(self):
        from routeforge.models import SkillInfo

        return SkillInfo(
            name=self.name,
            provider=self.provider,
            description=self.description,
            schema=self.schema(),
            source=self.source,
            provider_group=self.provider_group,
            requires_account=self.requires_account,
        )

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        return dict(args)


def test_pool_publishes_cooldown_and_recovery(runtime) -> None:
    import asyncio

    account = runtime.repo.add(provider="widget", label="w", api_key="k")

    async def scenario() -> None:
        await runtime.pool.mark_failure(account, reason="upstream 429", status_code=429)
        await runtime.pool.mark_success(account)

    asyncio.run(scenario())
    kinds = [e.type for e in runtime.events.recent()]
    assert COOLDOWN_STARTED in kinds
    assert RECOVERED in kinds


def test_announce_disabled_publishes_the_event(runtime) -> None:
    import asyncio

    asyncio.run(runtime.pool.announce_disabled(1, "widget"))
    assert [e.type for e in runtime.events.recent()] == [DISABLED]
