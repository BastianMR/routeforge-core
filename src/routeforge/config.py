"""Runtime settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

DEFAULT_HTTP_PORT = 8787
DEFAULT_EVENT_BUFFER_SIZE = 100
DEFAULT_USAGE_ROLLUP_SECONDS = 300
DEFAULT_USAGE_TICK_SECONDS = 60
DEFAULT_SSE_HEARTBEAT_SECONDS = 15


@dataclass(frozen=True)
class Settings:
    db_path: str
    master_key: str | None
    http_host: str
    http_port: int
    allow_public: bool
    default_cooldown_seconds: int
    plugins_dir: str = ""
    manifest_path: str | None = None
    event_buffer_size: int = DEFAULT_EVENT_BUFFER_SIZE
    usage_rollup_seconds: int = DEFAULT_USAGE_ROLLUP_SECONDS
    usage_tick_seconds: int = DEFAULT_USAGE_TICK_SECONDS
    sse_heartbeat_seconds: int = DEFAULT_SSE_HEARTBEAT_SECONDS
    mcp_http_port: int | None = None
    mcp_http_token: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=os.environ.get("ROUTE_FORGE_DB", _default_db_path()),
            master_key=os.environ.get("ROUTE_FORGE_MASTER_KEY"),
            http_host=os.environ.get("ROUTE_FORGE_HOST", "127.0.0.1"),
            http_port=int(os.environ.get("ROUTE_FORGE_PORT", str(DEFAULT_HTTP_PORT))),
            allow_public=os.environ.get("ROUTE_FORGE_ALLOW_PUBLIC", "0") == "1",
            default_cooldown_seconds=int(os.environ.get("ROUTE_FORGE_COOLDOWN", "60")),
            plugins_dir=os.environ.get("ROUTE_FORGE_PLUGINS_DIR", ""),
            manifest_path=os.environ.get("ROUTE_FORGE_MANIFEST_PATH"),
            event_buffer_size=_int_env(
                "ROUTE_FORGE_EVENT_BUFFER_SIZE", DEFAULT_EVENT_BUFFER_SIZE
            ),
            usage_rollup_seconds=_int_env(
                "ROUTE_FORGE_USAGE_ROLLUP_SECONDS", DEFAULT_USAGE_ROLLUP_SECONDS
            ),
            usage_tick_seconds=_int_env(
                "ROUTE_FORGE_USAGE_TICK_SECONDS", DEFAULT_USAGE_TICK_SECONDS
            ),
            sse_heartbeat_seconds=_int_env(
                "ROUTE_FORGE_SSE_HEARTBEAT_SECONDS", DEFAULT_SSE_HEARTBEAT_SECONDS
            ),
            mcp_http_port=_optional_int_env("ROUTE_FORGE_MCP_HTTP_PORT"),
            mcp_http_token=os.environ.get("ROUTE_FORGE_MCP_HTTP_TOKEN"),
        )

    def with_overrides(self, **kwargs: object) -> Settings:
        return replace(self, **kwargs)  # type: ignore[arg-type]

    def resolved_plugins_dir(self) -> str:
        from .plugins import default_plugins_dir

        return self.plugins_dir or default_plugins_dir()


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _default_db_path() -> str:
    """Default DB path: ~/.routeforge/routeforge.db."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".routeforge", "routeforge.db")
