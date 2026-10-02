"""Tests for `routeforge accounts`, `routeforge plugins`, and `routeforge tui`."""

from __future__ import annotations

import json
import shutil

import pytest
from typer.testing import CliRunner

from routeforge.cli import main as cli_main
from routeforge.cli.main import app
from routeforge.cli.plugins import _print_table

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from routeforge.secrets import Secrets

    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "plugins"))
    return tmp_path


def _add_account(provider: str = "firecrawl", label: str = "fc1", tags: str = "") -> None:
    args = ["accounts", "add", "--provider", provider, "--label", label, "--key", "k"]
    if tags:
        args += ["--tags", tags]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


# ------------------------------------------------------------------ accounts


def test_add_accepts_tags(env) -> None:
    _add_account(tags="scrape,web")
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert listed.exit_code == 0
    (account,) = json.loads(listed.stdout)
    assert account["tags"] == ["scrape", "web"]


def test_add_without_tags_defaults_to_empty(env) -> None:
    _add_account()
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert json.loads(listed.stdout)[0]["tags"] == []


def test_list_filters_by_provider_and_tag(env) -> None:
    _add_account(provider="firecrawl", label="fc1", tags="scrape")
    _add_account(provider="tavily", label="tv1", tags="search")

    by_provider = runner.invoke(app, ["accounts", "list", "--provider", "tavily", "--json"])
    assert [a["label"] for a in json.loads(by_provider.stdout)] == ["tv1"]

    by_tag = runner.invoke(app, ["accounts", "list", "--tag", "scrape", "--json"])
    assert [a["label"] for a in json.loads(by_tag.stdout)] == ["fc1"]


def test_list_never_prints_api_keys(env) -> None:
    _add_account()
    result = runner.invoke(app, ["accounts", "list"])
    assert "api_key" not in result.stdout


def test_tag_adds_tags(env) -> None:
    _add_account()
    result = runner.invoke(app, ["accounts", "tag", "fc1", "--add", "scrape,web"])
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert json.loads(listed.stdout)[0]["tags"] == ["scrape", "web"]


def test_untag_removes_only_the_named_tags(env) -> None:
    _add_account(tags="scrape,web")
    result = runner.invoke(app, ["accounts", "untag", "fc1", "--remove", "scrape"])
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert json.loads(listed.stdout)[0]["tags"] == ["web"]


def test_tag_requires_add_or_remove(env) -> None:
    _add_account()
    assert runner.invoke(app, ["accounts", "tag", "fc1"]).exit_code == 2


def test_tag_reports_a_missing_account(env) -> None:
    result = runner.invoke(app, ["accounts", "tag", "ghost", "--add", "x"])
    assert result.exit_code == 4
    assert "not found" in result.output


def test_untag_requires_remove(env) -> None:
    _add_account()
    assert runner.invoke(app, ["accounts", "untag", "fc1"]).exit_code != 0


def test_enable_and_disable(env) -> None:
    _add_account()
    assert runner.invoke(app, ["accounts", "disable", "fc1"]).exit_code == 0
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert json.loads(listed.stdout)[0]["enabled"] is False

    assert runner.invoke(app, ["accounts", "enable", "fc1"]).exit_code == 0
    listed = runner.invoke(app, ["accounts", "list", "--json"])
    assert json.loads(listed.stdout)[0]["enabled"] is True


def test_tags_command_lists_every_distinct_tag(env) -> None:
    _add_account(label="a", tags="web,scrape")
    _add_account(label="b", tags="scrape,search")
    result = runner.invoke(app, ["accounts", "tags"])
    assert result.exit_code == 0
    assert result.stdout.split() == ["scrape", "search", "web"]


# ------------------------------------------------------------------ plugins


def test_plugins_list_is_empty_by_default(env) -> None:
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0
    assert "no plugins" in result.stdout


def test_plugins_list_shows_the_error_column(env) -> None:
    from routeforge.plugins import Plugin, PluginRepo
    from routeforge.runtime import build_runtime

    runtime = build_runtime()
    PluginRepo(runtime.conn).upsert(
        Plugin(name="ok", source="plugin", module="m", attr="A", manifest_path="")
    )
    PluginRepo(runtime.conn).record_failure(
        Plugin(name="bad", source="plugin", module="nope", attr="B", manifest_path=""),
        "cannot import 'nope'",
    )
    runtime.conn.close()

    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0, result.output
    assert "error" in result.stdout
    assert "cannot import" in result.stdout


def test_plugins_list_json(env) -> None:
    result = runner.invoke(app, ["plugins", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_plugins_install_requires_confirmation(env) -> None:
    result = runner.invoke(app, ["plugins", "install", "https://github.com/me/skills"])
    assert result.exit_code == 1
    assert "--yes" in result.output
    assert "https://github.com/me/skills" in result.output


def test_plugins_install_reports_a_missing_git(env, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = runner.invoke(
        app, ["plugins", "install", "https://github.com/me/skills", "--yes"]
    )
    assert result.exit_code == 2
    assert "git" in result.output


def test_plugins_install_reports_a_clone_failure(env, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/git")

    class Failed:
        returncode = 128
        stderr = "fatal: repository not found"

    monkeypatch.setattr(cli_main.subprocess, "run", lambda *a, **k: Failed())
    result = runner.invoke(
        app, ["plugins", "install", "https://github.com/me/nope", "--yes"]
    )
    assert result.exit_code == 128
    assert "repository not found" in result.output


def test_plugins_install_registers_manifests(env, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/git")

    class Cloned:
        returncode = 0
        stderr = ""

    def fake_run(*_args, **_kwargs):
        target = env / "plugins" / "skills"
        target.mkdir(parents=True, exist_ok=True)
        (target / "demo.toml").write_text(
            'module = "m"\nattr = "A"\ninfo = { name = "demo", description = "d" }\n',
            encoding="utf-8",
        )
        return Cloned()

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)
    result = runner.invoke(
        app, ["plugins", "install", "https://github.com/me/skills", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "registered demo" in result.output



def test_print_table_handles_short_rows() -> None:
    _print_table([{"name": "a"}], ["name", "missing"])


# ---------------------------------------------------------------------- tui


def test_tui_reports_a_missing_binary(env, monkeypatch) -> None:
    monkeypatch.setattr(cli_main.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli_main, "locate_tui", lambda: None)
    result = runner.invoke(app, ["tui"])
    assert result.exit_code == 2
    assert "cargo build --release" in result.output


def test_locate_tui_prefers_path(env, monkeypatch) -> None:
    monkeypatch.setattr(cli_main.shutil, "which", lambda _name: "/opt/bin/routeforge-tui")
    found = cli_main.locate_tui()
    assert found is not None
    assert found.name == "routeforge-tui"


def test_tui_execs_the_binary(env, monkeypatch) -> None:
    class Done:
        returncode = 0

    monkeypatch.setattr(cli_main, "locate_tui", lambda: env / "routeforge-tui")
    monkeypatch.setattr(cli_main.subprocess, "run", lambda *a, **k: Done())
    result = runner.invoke(app, ["tui"])
    assert result.exit_code == 0


# ------------------------------------------------------------------ secrets


def test_secrets_generate_prints_a_key(env) -> None:
    result = runner.invoke(app, ["secrets", "generate"])
    assert result.exit_code == 0
    assert len(result.stdout.strip()) > 20


# -------------------------------------------------------------------- usage


def test_usage_show_defaults_to_the_summary(env) -> None:
    result = runner.invoke(app, ["usage", "show"])
    assert result.exit_code == 0
    assert "calls" in result.stdout


def test_usage_show_rejects_a_bad_group_by(env) -> None:
    result = runner.invoke(app, ["usage", "show", "--group-by", "nope"])
    assert result.exit_code == 2


def test_usage_prune_rejects_a_bad_duration(env) -> None:
    result = runner.invoke(app, ["usage", "prune", "--older-than", "soon"])
    assert result.exit_code == 2


def test_usage_prune_deletes_old_rows(env) -> None:
    from datetime import UTC, datetime, timedelta

    from routeforge.runtime import build_runtime

    runtime = build_runtime()
    runtime.usage.insert(
        "old", "success", 10, ts=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=200)
    )
    runtime.conn.close()

    result = runner.invoke(app, ["usage", "prune", "--older-than", "90d"])
    assert result.exit_code == 0, result.output
    assert "deleted 1" in result.output


def test_pool_command_prints_json(env) -> None:
    result = runner.invoke(app, ["pool"])
    assert result.exit_code == 0
    assert "accounts" in json.loads(result.stdout)


def test_commands_require_a_master_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ROUTE_FORGE_MASTER_KEY", raising=False)
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "nokey.db"))
    result = runner.invoke(app, ["accounts", "list"])
    assert result.exit_code == 3
    assert "ROUTE_FORGE_MASTER_KEY" in result.output


def test_help_is_available_for_every_command() -> None:
    for args in (
        ["--help"],
        ["skills", "--help"],
        ["plugins", "--help"],
        ["accounts", "--help"],
        ["events", "--help"],
        ["usage", "--help"],
        ["tui", "--help"],
    ):
        assert runner.invoke(app, args).exit_code == 0, args
