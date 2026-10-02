"""`routeforge plugins` commands."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import typer

from ..plugins import PluginDiscovery
from ..runtime import runtime_or_exit

app = typer.Typer(help="Inspect and install plugins")


@app.command("list")
def plugins_list(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Show every known plugin with its source, module, and state."""
    with runtime_or_exit() as runtime:
        rows = [p.model_dump() for p in runtime.plugin_repo.list()]
        if as_json:
            typer.echo(json.dumps(rows, indent=2, default=str))
            return
        if not rows:
            typer.echo("(no plugins installed)")
            return
        columns = ["name", "source", "module", "enabled", "loaded_at"]
        if any(not row["enabled"] for row in rows):
            columns.append("error")
        _print_table(rows, columns)


def _print_table(rows: list[dict], columns: list[str]) -> None:
    widths = {
        col: max(len(col), *(len(str(row.get(col, ""))) for row in rows))
        for col in columns
    }
    typer.echo("  ".join(col.ljust(widths[col]) for col in columns))
    for row in rows:
        typer.echo(
            "  ".join(str(row.get(col, "") or "").ljust(widths[col]) for col in columns)
        )


@app.command("install")
def plugins_install(
    url: str = typer.Argument(..., help="Git repository URL to clone."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation."
    ),
) -> None:
    """Clone a git repository into the plugins directory and register it.

    Plugins are trusted local code. The URL is echoed and confirmation is
    required before anything is fetched.
    """
    typer.echo(f"about to clone: {url}")
    if not yes:
        typer.echo("plugins execute arbitrary Python code. Re-run with --yes to proceed.")
        raise typer.Exit(code=1)

    if shutil.which("git") is None:
        typer.echo("error: git is not on PATH", err=True)
        raise typer.Exit(code=2)

    with runtime_or_exit() as runtime:
        target = Path(runtime.settings.resolved_plugins_dir()) / Path(url).stem
        result = subprocess.run(  # noqa: S603 - the URL is operator-supplied and echoed above
            ["git", "clone", "--depth", "1", url, str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            typer.echo(f"error: git clone failed: {result.stderr.strip()}", err=True)
            raise typer.Exit(code=result.returncode)

        found = PluginDiscovery.scan(target)
        typer.echo(f"cloned into {target}")
        if not found:
            typer.echo("no *.toml manifests found; nothing registered")
            return
        runtime.registry.reload()
        for plugin in found:
            typer.echo(f"registered {plugin.name} ({plugin.module}.{plugin.attr})")
        typer.echo(f"{len(found)} plugin(s) registered")
