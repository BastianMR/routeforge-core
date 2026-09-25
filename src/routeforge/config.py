"""Runtime settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    master_key: str | None
    http_host: str
    http_port: int
    allow_public: bool
    default_cooldown_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=os.environ.get("ROUTE_FORGE_DB", _default_db_path()),
            master_key=os.environ.get("ROUTE_FORGE_MASTER_KEY"),
            http_host=os.environ.get("ROUTE_FORGE_HOST", "127.0.0.1"),
            http_port=int(os.environ.get("ROUTE_FORGE_PORT", "8080")),
            allow_public=os.environ.get("ROUTE_FORGE_ALLOW_PUBLIC", "0") == "1",
            default_cooldown_seconds=int(os.environ.get("ROUTE_FORGE_COOLDOWN", "60")),
        )


def _default_db_path() -> str:
    """Default DB path: ~/.routeforge/routeforge.db."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".routeforge", "routeforge.db")
