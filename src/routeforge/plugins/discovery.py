"""Plugin manifest parsing, importing, and persistence.

Plugins are trusted local code. Discovery performs no network access; only an
explicit `routeforge plugins install <url>` ever fetches anything.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..models import PluginInfo
from ..skills.base import Skill

PLUGIN_SOURCE = "plugin"


class PluginError(RuntimeError):
    """A manifest is malformed, or its module could not be imported."""


@dataclass(frozen=True)
class Plugin:
    """A validated manifest, before the module is imported."""

    name: str
    module: str
    attr: str
    manifest_path: str
    description: str = ""
    provider: str = ""
    provider_group: str | None = None
    requires_account: bool = True
    source: str = PLUGIN_SOURCE


def default_plugins_dir() -> str:
    """`ROUTE_FORGE_PLUGINS_DIR`, else `~/.routeforge/plugins/`."""
    configured = os.environ.get("ROUTE_FORGE_PLUGINS_DIR")
    if configured:
        return configured
    return os.path.join(os.path.expanduser("~"), ".routeforge", "plugins")


class PluginDiscovery:
    @staticmethod
    def default_dir() -> str:
        return default_plugins_dir()

    @staticmethod
    def scan(plugins_dir: str | Path, reserved: set[str] | None = None) -> list[Plugin]:
        """Parse every `*.toml` in `plugins_dir`.

        A malformed manifest is reported on stderr and skipped, so one bad file
        never blocks startup. Use `scan_strict` to raise instead.
        """
        found: list[Plugin] = []
        for path in sorted(Path(plugins_dir).glob("*.toml")) if _exists(plugins_dir) else []:
            try:
                found.append(PluginDiscovery._parse(path, reserved))
            except PluginError as exc:
                print(f"routeforge: skipping plugin manifest {path}: {exc}", file=sys.stderr)
        return found

    @staticmethod
    def scan_strict(plugins_dir: str | Path, reserved: set[str] | None = None) -> list[Plugin]:
        """Same as `scan` but raises on the first malformed manifest."""
        found: list[Plugin] = []
        for path in sorted(Path(plugins_dir).glob("*.toml")) if _exists(plugins_dir) else []:
            found.append(PluginDiscovery._parse(path, reserved))
        return found

    @staticmethod
    def _parse(path: Path, reserved: set[str] | None) -> Plugin:
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise PluginError(f"unreadable manifest: {exc}") from exc

        for field in ("module", "attr", "info"):
            if field not in raw:
                raise PluginError(f"missing required field {field!r}")

        info = raw["info"]
        if not isinstance(info, dict):
            raise PluginError("field 'info' must be a table")
        name = info.get("name")
        if not name or not isinstance(name, str):
            raise PluginError("missing required field 'info.name'")
        if reserved and name in reserved:
            raise PluginError(f"name {name!r} collides with a built-in skill")

        return Plugin(
            name=name,
            module=str(raw["module"]),
            attr=str(raw["attr"]),
            manifest_path=str(path),
            description=str(info.get("description", "")),
            provider=str(info.get("provider", name)),
            provider_group=info.get("provider_group"),
            requires_account=bool(info.get("requires_account", True)),
            source=str(info.get("source", PLUGIN_SOURCE)),
        )

    @staticmethod
    def load(plugin: Plugin) -> Skill:
        """Import the module and instantiate the declared attribute."""
        try:
            module = importlib.import_module(plugin.module)
        except Exception as exc:  # noqa: BLE001 - any import-time error disables the plugin
            raise PluginError(f"cannot import {plugin.module!r}: {exc}") from exc

        attr = getattr(module, plugin.attr, None)
        if attr is None:
            raise PluginError(f"{plugin.module!r} has no attribute {plugin.attr!r}")
        if not isinstance(attr, type) or not issubclass(attr, Skill):
            raise PluginError(f"{plugin.module}.{plugin.attr} is not a Skill subclass")
        try:
            instance = attr()
        except Exception as exc:  # noqa: BLE001 - constructor failures are plugin bugs
            raise PluginError(f"cannot instantiate {plugin.module}.{plugin.attr}: {exc}") from exc

        # The manifest is the operator's declaration and wins over the
        # class-level defaults, so editing a TOML is enough to change behavior.
        instance.source = plugin.source  # type: ignore[misc]
        if plugin.provider:
            instance.provider = plugin.provider  # type: ignore[misc]
        if plugin.description:
            instance.description = plugin.description  # type: ignore[misc]
        if plugin.provider_group is not None:
            instance.provider_group = plugin.provider_group  # type: ignore[misc]
        instance.requires_account = plugin.requires_account  # type: ignore[misc]
        return instance


class PluginRepo:
    """CRUD on the `plugins` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, plugin: Plugin, error: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO plugins
                  (name, source, module_path, attr, manifest_path, enabled, loaded_at, error)
                VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(name) DO UPDATE SET
                  source = excluded.source,
                  module_path = excluded.module_path,
                  attr = excluded.attr,
                  manifest_path = excluded.manifest_path,
                  enabled = 1,
                  loaded_at = CURRENT_TIMESTAMP,
                  error = NULL
                """,
                (
                    plugin.name,
                    plugin.source,
                    plugin.module,
                    plugin.attr,
                    plugin.manifest_path,
                    error,
                ),
            )

    def set_enabled(self, name: str, enabled: bool, error: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE plugins SET enabled = ?, error = ? WHERE name = ?",
                (int(enabled), error, name),
            )

    def record_failure(self, plugin: Plugin, error: str) -> None:
        """Insert or update a row as disabled, preserving the error message.

        A plugin that never loaded still needs a row so `plugins list` and the
        TUI can show why it is missing.
        """
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO plugins
                  (name, source, module_path, attr, manifest_path, enabled, loaded_at, error)
                VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(name) DO UPDATE SET
                  enabled = 0,
                  error = excluded.error,
                  loaded_at = CURRENT_TIMESTAMP
                """,
                (
                    plugin.name,
                    plugin.source,
                    plugin.module,
                    plugin.attr,
                    plugin.manifest_path,
                    error,
                ),
            )

    def is_disabled(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT enabled FROM plugins WHERE name = ?", (name,)
        ).fetchone()
        return row is not None and not bool(row["enabled"])

    def set_error(self, name: str, error: str) -> None:
        self.set_enabled(name, False, error=error)

    def delete(self, name: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM plugins WHERE name = ?", (name,))

    def get(self, name: str) -> PluginInfo | None:
        row = self._conn.execute("SELECT * FROM plugins WHERE name = ?", (name,)).fetchone()
        return _to_info(row) if row is not None else None

    def list(self) -> list[PluginInfo]:
        rows = self._conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
        return [_to_info(r) for r in rows]

    def enabled_rows(self) -> list[PluginInfo]:
        rows = self._conn.execute(
            "SELECT * FROM plugins WHERE enabled = 1 ORDER BY manifest_path, name"
        ).fetchall()
        return [_to_info(r) for r in rows]


def _to_info(row: sqlite3.Row) -> PluginInfo:
    return PluginInfo(
        name=row["name"],
        source=row["source"],
        module=row["module_path"],
        attr=row["attr"],
        manifest_path=row["manifest_path"],
        enabled=bool(row["enabled"]),
        loaded_at=row["loaded_at"],
        error=row["error"],
        missing_source=bool(row["manifest_path"]) and not Path(row["manifest_path"]).exists(),
    )


def _exists(path: str | Path) -> bool:
    return Path(path).is_dir()
