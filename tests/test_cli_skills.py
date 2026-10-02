"""`routeforge skills` commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from routeforge.cli.main import app

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from routeforge.secrets import Secrets

    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "plugins"))
    return tmp_path


def _manifest(plugins_dir: Path, module: str = "reloadable_skill") -> Path:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    path = plugins_dir / "reloadable.toml"
    path.write_text(
        f'module = "{module}"\n'
        'attr = "ReloadableSkill"\n'
        'info = { name = "reloadable", description = "From a manifest." }\n',
        encoding="utf-8",
    )
    return path


def test_list_shows_the_required_columns(env) -> None:
    result = runner.invoke(app, ["skills", "list"])
    assert result.exit_code == 0
    for column in ("name", "source", "requires_account", "provider_group"):
        assert column in result.stdout
    assert "echo" in result.stdout
    assert "firecrawl/scrape" in result.stdout


def test_list_json_output(env) -> None:
    result = runner.invoke(app, ["skills", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {s["name"] for s in payload} >= {"echo", "firecrawl/scrape"}
    assert all("source" in s for s in payload)


def test_list_filters_by_source(env, tmp_path) -> None:
    module_root = tmp_path / "src"
    module_root.mkdir(parents=True, exist_ok=True)
    (module_root / "reloadable_skill.py").write_text(
        "from typing import Any\n"
        "import httpx\n"
        "from routeforge.models import Account, SkillSchemaModel\n"
        "from routeforge.skills.base import Skill\n"
        "\n"
        "class ReloadableSkill(Skill):\n"
        '    name = "reloadable"\n'
        '    provider = "widget"\n'
        '    description = "d"\n'
        "    async def execute(self, a: Account, g: dict[str, Any], h: httpx.AsyncClient) -> dict:\n"
        "        return {}\n",
        encoding="utf-8",
    )
    import sys

    sys.path.insert(0, str(module_root))
    try:
        _manifest(tmp_path / "plugins")
        assert runner.invoke(app, ["skills", "list"]).exit_code == 0
        plugin_only = runner.invoke(app, ["skills", "list", "--source", "plugin", "--json"])
        assert plugin_only.exit_code == 0
        payload = json.loads(plugin_only.stdout)
        assert [s["name"] for s in payload] == ["reloadable"]
    finally:
        sys.path.remove(str(module_root))
        sys.modules.pop("reloadable_skill", None)


def test_add_registers_and_persists_the_manifest(env, tmp_path) -> None:
    module_root = tmp_path / "src"
    module_root.mkdir(parents=True, exist_ok=True)
    (module_root / "reloadable_skill.py").write_text(
        "from typing import Any\n"
        "import httpx\n"
        "from routeforge.models import Account, SkillSchemaModel\n"
        "from routeforge.skills.base import Skill\n"
        "\n"
        "class ReloadableSkill(Skill):\n"
        '    name = "reloadable"\n'
        '    provider = "widget"\n'
        '    description = "d"\n'
        "    async def execute(self, a: Account, g: dict[str, Any], h: httpx.AsyncClient) -> dict:\n"
        "        return {}\n",
        encoding="utf-8",
    )
    import sys

    sys.path.insert(0, str(module_root))
    try:
        manifest = _manifest(tmp_path / "plugins")
        result = runner.invoke(app, ["skills", "add", "--from-toml", str(manifest)])
        assert result.exit_code == 0, result.output
        assert "reloadable" in result.stdout

        listed = runner.invoke(app, ["skills", "list", "--json"])
        assert "reloadable" in {s["name"] for s in json.loads(listed.stdout)}
    finally:
        sys.path.remove(str(module_root))
        sys.modules.pop("reloadable_skill", None)


def test_add_reports_a_bad_manifest(env, tmp_path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('module = "a.b"\n', encoding="utf-8")
    result = runner.invoke(app, ["skills", "add", "--from-toml", str(bad)])
    assert result.exit_code != 0


def test_add_requires_from_toml(env) -> None:
    assert runner.invoke(app, ["skills", "add"]).exit_code != 0


def test_remove_unregisters_and_deletes_the_row(env) -> None:
    from routeforge.plugins import Plugin, PluginRepo
    from routeforge.runtime import build_runtime

    runtime = build_runtime()
    PluginRepo(runtime.conn).upsert(
        Plugin(
            name="ghost",
            source="plugin",
            module="m",
            attr="A",
            manifest_path="",
        )
    )
    runtime.registry.register(_Fake(), "plugin")
    runtime.conn.close()

    result = runner.invoke(app, ["skills", "remove", "ghost"])
    assert result.exit_code == 0
    assert "ghost" in result.stdout

    after = build_runtime()
    try:
        assert PluginRepo(after.conn).get("ghost") is None
    finally:
        after.conn.close()


def test_remove_reports_an_unknown_skill(env) -> None:
    result = runner.invoke(app, ["skills", "remove", "nope"])
    assert result.exit_code != 0


def test_reload_emits_the_diff(env, tmp_path) -> None:
    result = runner.invoke(app, ["skills", "reload"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload) == {"added", "removed", "updated"}


class _Fake:
    """Duck-typed skill so the CLI can unregister a name without the ABC."""

    name = "ghost"
    provider = "widget"
    description = "d"
    requires_account = True
    provider_group = None
    source = "plugin"
