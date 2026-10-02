"""Tests for registry reload, source metadata, and plugin persistence."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from routeforge.plugins import PluginRepo
from routeforge.skills.registry import SkillRegistry

PLUGIN_MODULE = '''
    from __future__ import annotations

    from typing import Any

    import httpx

    from routeforge.models import Account, SkillSchemaModel
    from routeforge.skills.base import Skill


    class ReloadableSkill(Skill):
        name = "reloadable"
        provider = "widget"
        description = "Loaded from a plugin manifest."

        def schema(self) -> SkillSchemaModel:
            return SkillSchemaModel()

        async def execute(self, account, args, http):
            return {}
'''


@pytest.fixture
def workspace(tmp_path: Path):
    """A sys.path entry plus a plugins directory, cleaned up afterwards."""
    module_root = tmp_path / "src"
    plugins_dir = tmp_path / "plugins"
    module_root.mkdir(parents=True)
    (module_root / "reloadable_skill.py").write_text(
        textwrap.dedent(PLUGIN_MODULE), encoding="utf-8"
    )
    plugins_dir.mkdir()
    sys.path.insert(0, str(module_root))
    try:
        yield module_root, plugins_dir
    finally:
        sys.path.remove(str(module_root))
        sys.modules.pop("reloadable_skill", None)


def _manifest(plugins_dir: Path, name: str = "reloadable.toml") -> Path:
    path = plugins_dir / name
    path.write_text(
        'module = "reloadable_skill"\n'
        'attr = "ReloadableSkill"\n'
        'info = { name = "reloadable", description = "Loaded from a plugin manifest." }\n',
        encoding="utf-8",
    )
    return path


def test_builtin_discovery_marks_source_builtin() -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    assert registry.source("echo") == "builtin"
    assert registry.source("firecrawl/scrape") == "builtin"
    assert registry.info("echo").source == "builtin"
    assert registry.info("echo").provider_group is None
    assert registry.info("echo").requires_account is False


def test_reload_picks_up_a_new_manifest(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    repo = PluginRepo(conn)
    bus = None
    registry = SkillRegistry(plugin_repo=repo, events=bus, plugins_dirs=[str(plugins_dir)])
    registry.load_all()

    assert registry.get("reloadable") is None

    _manifest(plugins_dir)
    diff = registry.reload()

    assert diff["added"] == ["reloadable"]
    assert diff["removed"] == []
    assert registry.source("reloadable") == "plugin"
    assert repo.get("reloadable") is not None
    assert repo.get("reloadable").enabled is True


def test_reload_removes_a_manifest_and_disables_the_row(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    _manifest(plugins_dir)
    repo = PluginRepo(conn)
    registry = SkillRegistry(plugin_repo=repo, events=None, plugins_dirs=[str(plugins_dir)])
    registry.load_all()
    assert registry.get("reloadable") is not None

    (plugins_dir / "reloadable.toml").unlink()
    diff = registry.reload()

    assert diff["removed"] == ["reloadable"]
    info = repo.get("reloadable")
    assert info is not None
    assert info.enabled is False
    assert info.error


def test_reload_reports_updated(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    manifest = _manifest(plugins_dir)
    repo = PluginRepo(conn)
    registry = SkillRegistry(plugin_repo=repo, events=None, plugins_dirs=[str(plugins_dir)])
    registry.load_all()

    manifest.write_text(
        'module = "reloadable_skill"\n'
        'attr = "ReloadableSkill"\n'
        'info = { name = "reloadable", description = "Changed description.", provider_group = "widget" }\n',
        encoding="utf-8",
    )
    diff = registry.reload()

    assert diff["updated"] == ["reloadable"]
    assert registry.info("reloadable").provider_group == "widget"


def test_reload_emits_skill_reloaded_event(workspace, conn) -> None:
    from routeforge.events import EventBus

    _module_root, plugins_dir = workspace
    bus = EventBus()
    registry = SkillRegistry(plugin_repo=PluginRepo(conn), events=bus, plugins_dirs=[str(plugins_dir)])
    registry.load_all()
    bus.recent()
    _manifest(plugins_dir)
    registry.reload()

    reloaded = [e for e in bus.recent() if e.type == "skill.reloaded"]
    assert len(reloaded) == 1
    assert reloaded[0].data["added"] == ["reloadable"]


def test_reload_emits_mcp_list_changed_notification(workspace, conn) -> None:
    from routeforge.events import EventBus

    _module_root, plugins_dir = workspace
    bus = EventBus()
    registry = SkillRegistry(plugin_repo=PluginRepo(conn), events=bus, plugins_dirs=[str(plugins_dir)])
    registry.load_all()
    _manifest(plugins_dir)
    registry.reload()

    kinds = [e.type for e in bus.recent()]
    assert "mcp.tools.list_changed" in kinds


def test_disabled_plugin_row_is_not_imported(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    _manifest(plugins_dir)
    repo = PluginRepo(conn)
    repo.upsert(
        __import__("routeforge.plugins", fromlist=["Plugin"]).Plugin(
            name="reloadable",
            source="plugin",
            module="reloadable_skill",
            attr="ReloadableSkill",
            manifest_path=str(plugins_dir / "reloadable.toml"),
        )
    )
    repo.set_enabled("reloadable", False, error="previous failure")

    registry = SkillRegistry(plugin_repo=repo, events=None, plugins_dirs=[str(plugins_dir)])
    registry.load_all()
    assert registry.get("reloadable") is None


def test_import_failure_disables_the_row(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    (plugins_dir / "broken.toml").write_text(
        'module = "not_importable"\n'
        'attr = "Thing"\n'
        'info = { name = "broken", description = "nope" }\n',
        encoding="utf-8",
    )
    repo = PluginRepo(conn)
    registry = SkillRegistry(plugin_repo=repo, events=None, plugins_dirs=[str(plugins_dir)])
    registry.load_all()  # must not raise

    assert registry.get("broken") is None
    info = repo.get("broken")
    assert info is not None
    assert info.enabled is False
    assert "not_importable" in (info.error or "")


def test_plugin_cannot_shadow_a_builtin(workspace, conn) -> None:
    _module_root, plugins_dir = workspace
    (plugins_dir / "echo-clash.toml").write_text(
        'module = "reloadable_skill"\n'
        'attr = "ReloadableSkill"\n'
        'info = { name = "echo", description = "clash" }\n',
        encoding="utf-8",
    )
    repo = PluginRepo(conn)
    registry = SkillRegistry(plugin_repo=repo, events=None, plugins_dirs=[str(plugins_dir)])
    registry.load_all()

    assert registry.info("echo").source == "builtin"


def test_list_includes_source_metadata() -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    names = {info.name for info in registry.list_all()}
    assert {"echo", "firecrawl/scrape"} <= names
    assert all(info.source == "builtin" for info in registry.list_all())
