"""`routeforge skills` commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..plugins import Plugin, PluginDiscovery, PluginError, PluginRepo
from ..runtime import runtime_or_exit

app = typer.Typer(help="Inspect and manage skills")

VALID_SOURCES = ("builtin", "plugin", "manifest", "all")


def _echo_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _print_table(rows: list[dict], columns: list[str]) -> None:
    if not rows:
        typer.echo("(none)")
        return
    widths = {
        col: max(len(col), *(len(str(row.get(col, ""))) for row in rows))
        for col in columns
    }
    typer.echo("  ".join(col.ljust(widths[col]) for col in columns))
    for row in rows:
        typer.echo(
            "  ".join(str(row.get(col, "") or "").ljust(widths[col]) for col in columns)
        )


def _missing_source(plugin_repo: PluginRepo, name: str) -> bool:
    row = plugin_repo.get(name)
    return row is not None and row.missing_source


@app.command("list")
def skills_list(
    source: str = typer.Option("all", help="builtin | plugin | manifest | all"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List registered skills with their source."""
    if source not in VALID_SOURCES:
        typer.echo(f"error: source must be one of {', '.join(VALID_SOURCES)}", err=True)
        raise typer.Exit(code=2)
    with runtime_or_exit() as runtime:
        rows = [
            info.model_dump()
            for info in runtime.registry.by_source(None if source == "all" else source)
        ]
        for row in rows:
            if _missing_source(runtime.plugin_repo, row["name"]):
                row["missing_source"] = True
        if as_json:
            _echo_json(rows)
            return
        _print_table(rows, ["name", "source", "requires_account", "provider_group"])


@app.command("add")
def skills_add(
    from_toml: Path = typer.Option(..., "--from-toml", help="Path to a plugin manifest."),
) -> None:
    """Load a skill from a manifest and persist it.

    Only built-in names are reserved: re-adding a plugin that is already
    loaded from the plugins directory is allowed and simply re-registers it.
    """
    with runtime_or_exit() as runtime:
        builtin = {s.name for s in runtime.registry.list() if s.source == "builtin"}
        try:
            plugin = PluginDiscovery._parse(from_toml, builtin)
        except PluginError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        _register(runtime, plugin)


def _register(runtime, plugin: Plugin) -> None:
    try:
        skill = PluginDiscovery.load(plugin)
    except PluginError as exc:
        runtime.plugin_repo.record_failure(plugin, str(exc))
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    runtime.registry.register(skill, plugin.source)
    runtime.plugin_repo.upsert(plugin)
    typer.echo(f"added skill {skill.name} from {plugin.manifest_path}")


@app.command("remove")
def skills_remove(
    name: str = typer.Argument(..., help="Skill name to unregister."),
) -> None:
    """Unregister a skill, delete its plugins row, and reload."""
    with runtime_or_exit() as runtime:
        registered = name in runtime.registry.names()
        persisted = runtime.plugin_repo.get(name) is not None
        if not registered and not persisted:
            typer.echo(f"error: skill not found: {name}", err=True)
            raise typer.Exit(code=4)
        runtime.registry.unregister(name)
        runtime.plugin_repo.delete(name)
        diff = runtime.registry.reload()
        typer.echo(f"removed skill {name}: {json.dumps(diff)}")


@app.command("reload")
def skills_reload() -> None:
    """Re-scan every source and print the diff."""
    with runtime_or_exit() as runtime:
        _echo_json(runtime.registry.reload())
