"""Object graph shared by the HTTP server, the MCP server, and the CLI.

Keeping assembly in one place means `serve`, `mcp`, and every CLI command see
the same registry, pool, event bus, and repositories.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from .accounts import AccountRepo
from .config import Settings
from .db import connect
from .events import EventBus
from .events.bus import USAGE_TICK
from .plugins import PluginRepo
from .rotation import RoundRobinPool
from .router import Router
from .secrets import Secrets
from .skills.registry import SkillRegistry
from .usage import UsageLogRepo


@dataclass
class Runtime:
    settings: Settings
    secrets: Secrets
    conn: Any
    repo: AccountRepo
    pool: RoundRobinPool
    registry: SkillRegistry
    plugin_repo: PluginRepo
    usage: UsageLogRepo
    events: EventBus
    router: Router
    http: httpx.AsyncClient
    # Set when an MCP server is attached, so a reload can notify the calling
    # session over the MCP transport.
    mcp_server: Any = None

    async def aclose(self) -> None:
        await self.http.aclose()
        self.conn.close()

    async def usage_rollup_loop(self) -> None:
        """Fill `usage_daily` on a fixed interval for as long as the app runs."""
        interval = self.settings.usage_rollup_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                self.usage.rollup()
            except Exception:  # noqa: BLE001 - a failed rollup must not kill the server
                continue

    async def usage_tick_loop(self) -> None:
        """Publish a `usage.tick` event so the TUI footer stays live."""
        from .usage import parse_since

        while True:
            await asyncio.sleep(self.settings.usage_tick_seconds)
            try:
                requests, errors = self.usage.counts(parse_since("1m"))
            except Exception:  # noqa: BLE001 - never let telemetry kill the server
                continue
            self.events.emit(USAGE_TICK, window="1m", requests=requests, errors=errors)


def build_runtime(settings: Settings | None = None) -> Runtime:
    """Assemble the gateway. Raises `RuntimeError` when the master key is absent."""
    settings = settings or Settings.from_env()
    if not settings.master_key:
        raise RuntimeError("ROUTE_FORGE_MASTER_KEY is required")

    secrets = Secrets(settings.master_key)
    conn = connect(settings.db_path)
    repo = AccountRepo(conn, secrets)
    plugin_repo = PluginRepo(conn)
    usage = UsageLogRepo(conn)
    events = EventBus(buffer_size=settings.event_buffer_size)
    pool = RoundRobinPool(repo, default_cooldown_seconds=settings.default_cooldown_seconds, events=events)
    registry = SkillRegistry(
        plugin_repo=plugin_repo,
        events=events,
        plugins_dirs=[settings.resolved_plugins_dir()],
    )
    registry.load_all()
    http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    router = Router(repo, pool, registry, http, conn, usage=usage, events=events)
    return Runtime(
        settings=settings,
        secrets=secrets,
        conn=conn,
        repo=repo,
        pool=pool,
        registry=registry,
        plugin_repo=plugin_repo,
        usage=usage,
        events=events,
        router=router,
        http=http,
    )


@contextlib.contextmanager
def runtime_or_exit(settings: Settings | None = None) -> Iterator[Runtime]:
    """`build_runtime` for CLI paths that should print a clean error and exit."""
    try:
        instance = build_runtime(settings)
    except RuntimeError as exc:
        import typer

        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    try:
        yield instance
    finally:
        with contextlib.suppress(Exception):
            instance.conn.close()
