"""Skill discovery, lookup, and reload."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING, Any

from ..models import SkillInfo
from .base import Skill

if TYPE_CHECKING:
    from ..events import EventBus
    from ..plugins import PluginRepo

BUILTIN_SOURCE = "builtin"
RELOADED_EVENT = "skill.reloaded"
LIST_CHANGED_EVENT = "mcp.tools.list_changed"


class SkillRegistry:
    """Holds every loaded skill, keyed by name.

    Three sources are supported: the `routeforge.skills.builtin` package
    (always loaded), TOML plugin manifests on disk, and plugins persisted in
    the `plugins` table. Tags and provider groups are a routing concern; the
    registry only records where each skill came from.
    """

    def __init__(
        self,
        plugin_repo: PluginRepo | None = None,
        events: EventBus | None = None,
        plugins_dirs: list[str] | None = None,
        builtin_package: str = "routeforge.skills.builtin",
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._sources: dict[str, str] = {}
        self._plugin_repo = plugin_repo
        self._events = events
        self._plugins_dirs = plugins_dirs
        self._builtin_package = builtin_package

    def register(self, skill: Skill, source: str | None = None) -> None:
        if not skill.name:
            raise ValueError("skill.name must be non-empty")
        resolved = source or skill.source or BUILTIN_SOURCE
        skill.source = resolved  # type: ignore[misc]
        self._skills[skill.name] = skill
        self._sources[skill.name] = resolved

    def unregister(self, name: str) -> Skill | None:
        self._sources.pop(name, None)
        return self._skills.pop(name, None)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def list_all(self) -> list[SkillInfo]:
        """Every registered skill as a `SkillInfo`, source included."""
        return [skill.info for skill in self._skills.values()]

    def info(self, name: str) -> SkillInfo:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"skill not found: {name}")
        return skill.info

    def source(self, skill_name: str) -> str:
        """`"builtin"`, `"plugin"`, or `"manifest"`."""
        return self._sources.get(skill_name, BUILTIN_SOURCE)

    def names(self) -> set[str]:
        return set(self._skills)

    def by_source(self, source: str | None = None) -> list[SkillInfo]:
        if source in (None, "all"):
            return self.list_all()
        return [info for info in self.list_all() if info.source == source]

    def discover_builtin(self, package: str | None = None) -> int:
        """Walk the package and register every Skill subclass found. Returns count."""
        package = package or self._builtin_package
        pkg = importlib.import_module(package)
        count = 0
        for _finder, module_name, _is_pkg in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}."):
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if obj is Skill:
                    continue
                if not issubclass(obj, Skill):
                    continue
                if obj.__module__ != module.__name__:
                    continue
                try:
                    instance = obj()
                except Exception:
                    continue
                if instance.name:
                    self.register(instance, BUILTIN_SOURCE)
                    count += 1
        return count

    def load_external(self, sources: list[str] | None = None) -> list[str]:
        """Scan every plugins directory and load the manifests found.

        Returns the names of the skills that loaded successfully.
        """
        from ..plugins import PluginDiscovery, PluginError

        dirs = sources if sources is not None else (self._plugins_dirs or [])
        loaded: list[str] = []
        for directory in dirs:
            reserved = set(self._skills)
            for plugin in PluginDiscovery.scan(directory, reserved=reserved):
                if plugin.name in self._skills:
                    continue
                # A row marked disabled (import failure, operator opt-out) is
                # never re-imported, even if the manifest is still on disk.
                if self._plugin_repo is not None and self._plugin_repo.is_disabled(plugin.name):
                    continue
                try:
                    skill = PluginDiscovery.load(plugin)
                except PluginError as exc:
                    self._record_failure(plugin, str(exc))
                    continue
                self.register(skill, plugin.source)
                self._record_success(plugin)
                loaded.append(skill.name)
        return loaded

    def load_persisted(self) -> list[str]:
        """Re-import plugins stored in the `plugins` table with `enabled=1`.

        A row whose manifest has disappeared from disk is disabled with an
        explanatory error rather than crashing startup.
        """
        from pathlib import Path

        from ..plugins import Plugin, PluginDiscovery, PluginError

        if self._plugin_repo is None:
            return []
        loaded: list[str] = []
        for row in self._plugin_repo.enabled_rows():
            # A manifest still on disk is authoritative: it carries fields the
            # table does not store, such as provider_group. Only fall back to
            # the row for plugins that are no longer on disk.
            if row.name in self._skills:
                continue
            if row.manifest_path and not Path(row.manifest_path).exists():
                self._plugin_repo.set_error(
                    row.name, f"manifest not found at {row.manifest_path}"
                )
                continue
            if not row.module or not row.attr:
                self._plugin_repo.set_error(
                    row.name, "plugin row is missing its module or attr"
                )
                continue
            plugin = Plugin(
                name=row.name,
                module=row.module,
                attr=row.attr,
                manifest_path=row.manifest_path or "",
                source=row.source,
            )
            try:
                skill = PluginDiscovery.load(plugin)
            except PluginError as exc:
                self._plugin_repo.set_error(row.name, str(exc))
                continue
            self.register(skill, row.source)
            loaded.append(skill.name)
        return loaded

    def load_all(self) -> None:
        """Full startup sequence: builtins, then disk manifests, then persisted rows."""
        self.discover_builtin()
        self.load_external()
        self.load_persisted()

    def reload(self) -> dict[str, list[str]]:
        """Clear, re-scan every source, and report the diff.

        Emits `skill.reloaded` followed by `mcp.tools.list_changed` so connected
        MCP sessions refresh their tool list.
        """
        previous = {name: self._describe(skill) for name, skill in self._skills.items()}
        self._skills.clear()
        self._sources.clear()
        self.load_all()
        current = {name: self._describe(skill) for name, skill in self._skills.items()}

        diff = {
            "added": sorted(set(current) - set(previous)),
            "removed": sorted(set(previous) - set(current)),
            "updated": sorted(
                name
                for name in set(previous) & set(current)
                if previous[name] != current[name]
            ),
        }
        self._emit(RELOADED_EVENT, **diff)
        self._emit(LIST_CHANGED_EVENT, reason="registry.reload", **diff)
        return diff

    def _describe(self, skill: Skill) -> tuple[Any, ...]:
        return (
            skill.provider,
            skill.description,
            skill.provider_group,
            skill.source,
            getattr(skill, "requires_account", True),
        )

    def _record_success(self, plugin: Any) -> None:
        if self._plugin_repo is not None:
            self._plugin_repo.upsert(plugin)

    def _record_failure(self, plugin: Any, error: str) -> None:
        if self._plugin_repo is not None:
            self._plugin_repo.record_failure(plugin, error)

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._events is not None:
            self._events.emit(event_type, **data)
