"""Tests for TOML plugin manifests and the plugin repository."""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

from routeforge.plugins import Plugin, PluginDiscovery, PluginError, PluginRepo


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    return tmp_path / "plugins"


def _write_module(root: Path, dotted: str, source: str) -> None:
    """Create an importable module on sys.path."""
    path = root / Path(*dotted.split(".")).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def _write_manifest(plugins_dir: Path, filename: str, body: str) -> Path:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    path = plugins_dir / filename
    path.write_text(body, encoding="utf-8")
    return path


VALID_MODULE = '''
    from __future__ import annotations

    from typing import Any

    import httpx

    from routeforge.models import Account, SkillSchemaModel
    from routeforge.skills.base import Skill


    class WebScrapeSkill(Skill):
        name = "web-scrape"
        provider = "web"
        description = "Scrape via a plugin."
        provider_group = "scrape"

        def schema(self) -> SkillSchemaModel:
            return SkillSchemaModel(inputs={"type": "object"}, outputs={"type": "object"})

        async def execute(self, account, args, http):
            return {"args": args, "tags": account.tags}
'''


def test_valid_manifest_loads_a_plugin(tmp_path: Path, plugins_dir: Path) -> None:
    _write_module(tmp_path, "my_skills.scraper", VALID_MODULE)
    _write_module(tmp_path, "my_skills.__init__", "")
    sys.path.insert(0, str(tmp_path))
    try:
        _write_manifest(
            plugins_dir,
            "web-scrape.toml",
            """
            module = "my_skills.scraper"
            attr = "WebScrapeSkill"

            [info]
            name = "web-scrape"
            description = "Scrape via a plugin."
            requires_account = true
            provider_group = "scrape"
            """,
        )
        plugins = PluginDiscovery.scan(plugins_dir)
        assert len(plugins) == 1
        plugin = plugins[0]
        assert plugin.name == "web-scrape"
        assert plugin.module == "my_skills.scraper"
        assert plugin.source == "plugin"
        assert plugin.manifest_path.endswith("web-scrape.toml")

        skill = PluginDiscovery.load(plugin)
        assert skill.name == "web-scrape"
        assert skill.info.provider_group == "scrape"
        assert skill.info.source == "plugin"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("my_skills.scraper", None)
        sys.modules.pop("my_skills", None)


def test_manifest_missing_field_is_rejected(plugins_dir: Path, capsys) -> None:
    _write_manifest(plugins_dir, "bad.toml", 'module = "a.b"\n')
    plugins = PluginDiscovery.scan(plugins_dir)
    assert plugins == []
    assert "bad.toml" in capsys.readouterr().err


def test_manifest_with_unknown_field_names_is_rejected(plugins_dir: Path) -> None:
    _write_manifest(
        plugins_dir,
        "no-name.toml",
        """
        module = "a.b"
        attr = "Thing"
        info = { description = "no name here" }
        """,
    )
    with pytest.raises(PluginError, match="name"):
        PluginDiscovery.scan_strict(plugins_dir)


def test_import_failure_raises_plugin_error(tmp_path: Path, plugins_dir: Path) -> None:
    _write_manifest(
        plugins_dir,
        "missing.toml",
        """
        module = "does_not_exist_anywhere"
        attr = "Thing"
        info = { name = "missing", description = "nope" }
        """,
    )
    (plugin,) = PluginDiscovery.scan(plugins_dir)
    with pytest.raises(PluginError):
        PluginDiscovery.load(plugin)


def test_attr_must_be_a_skill_subclass(tmp_path: Path, plugins_dir: Path) -> None:
    _write_module(tmp_path, "plain_thing", "class Thing:\n    pass\n")
    sys.path.insert(0, str(tmp_path))
    try:
        _write_manifest(
            plugins_dir,
            "plain.toml",
            """
            module = "plain_thing"
            attr = "Thing"
            info = { name = "plain", description = "not a skill" }
            """,
        )
        (plugin,) = PluginDiscovery.scan(plugins_dir)
        with pytest.raises(PluginError, match="Skill"):
            PluginDiscovery.load(plugin)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("plain_thing", None)


def test_builtin_name_collision_is_rejected(plugins_dir: Path) -> None:
    _write_manifest(
        plugins_dir,
        "collide.toml",
        """
        module = "some.module"
        attr = "Echo"
        info = { name = "echo", description = "collides with builtin" }
        """,
    )
    with pytest.raises(PluginError, match="echo"):
        PluginDiscovery.scan_strict(plugins_dir, reserved={"echo"})


def test_scan_on_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert PluginDiscovery.scan(tmp_path / "nope") == []


def test_plugin_repo_round_trip(conn) -> None:
    repo = PluginRepo(conn)
    repo.upsert(
        Plugin(
            name="web-scrape",
            source="plugin",
            module="my_skills.scraper",
            attr="WebScrapeSkill",
            manifest_path="~/.routeforge/plugins/web-scrape.toml",
        )
    )
    (info,) = repo.list()
    assert info.name == "web-scrape"
    assert info.module == "my_skills.scraper"
    assert info.enabled is True
    assert info.error is None
    assert info.loaded_at is not None

    repo.set_enabled("web-scrape", False, error="No module named 'my_skills'")
    (info,) = repo.list()
    assert info.enabled is False
    assert info.error == "No module named 'my_skills'"

    repo.delete("web-scrape")
    assert repo.list() == []


def test_plugin_repo_delete_missing_is_noop(conn) -> None:
    PluginRepo(conn).delete("absent")


def test_default_plugins_dir(monkeypatch) -> None:
    monkeypatch.delenv("ROUTE_FORGE_PLUGINS_DIR", raising=False)
    assert PluginDiscovery.default_dir().endswith(os.path.join(".routeforge", "plugins"))


def test_plugins_dir_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "custom"))
    assert PluginDiscovery.default_dir() == str(tmp_path / "custom")
