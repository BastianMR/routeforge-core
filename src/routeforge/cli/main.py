"""Typer CLI for routeforge-core."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from ..config import Settings
from ..runtime import build_runtime, runtime_or_exit
from ..secrets import Secrets
from . import accounts as accounts_cli
from . import events as events_cli
from . import plugins as plugins_cli
from . import skills as skills_cli
from . import usage as usage_cli

app = typer.Typer(help="routeforge-core CLI", no_args_is_help=True)
secrets_app = typer.Typer(help="Manage encryption")
app.add_typer(accounts_cli.app, name="accounts")
app.add_typer(secrets_app, name="secrets")
app.add_typer(skills_cli.app, name="skills")
app.add_typer(plugins_cli.app, name="plugins")
app.add_typer(events_cli.app, name="events")
app.add_typer(usage_cli.app, name="usage")


@secrets_app.command("generate")
def secrets_generate() -> None:
    """Print a fresh Fernet master key."""
    typer.echo(Secrets.generate_key())


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Override ROUTE_FORGE_HOST."),
    port: int | None = typer.Option(None, help="Override ROUTE_FORGE_PORT."),
) -> None:
    """Run the HTTP server."""
    import uvicorn

    from ..app import _validate_bind, create_app

    settings = Settings.from_env()
    overrides: dict[str, object] = {}
    if host:
        overrides["http_host"] = host
    if port:
        overrides["http_port"] = port
    if overrides:
        settings = settings.with_overrides(**overrides)

    _validate_bind(settings)
    try:
        runtime = build_runtime(settings)
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    uvicorn.run(
        create_app(runtime),
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )


@app.command()
def mcp(
    http: bool = typer.Option(
        False, "--http", help="Serve MCP over streamable HTTP instead of stdio."
    ),
) -> None:
    """Run the MCP server over stdio, or over HTTP when ROUTE_FORGE_MCP_HTTP_PORT is set."""
    from ..mcp_server import run_http, run_stdio

    try:
        runtime = build_runtime()
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    port = runtime.settings.mcp_http_port
    if http and port is None:
        typer.echo("error: --http requires ROUTE_FORGE_MCP_HTTP_PORT", err=True)
        raise typer.Exit(code=2)
    if port is not None:
        run_http(runtime, port, runtime.settings.mcp_http_token)
        return
    run_stdio(runtime)


@app.command()
def tui() -> None:
    """Launch the bundled Rust TUI binary."""
    binary = locate_tui()
    if binary is None:
        typer.echo(
            "error: routeforge-tui binary not found.\n"
            "Build it with:\n"
            "  cargo build --release --manifest-path crates/routeforge-tui/Cargo.toml\n"
            "then re-run `routeforge tui`, or put the binary on PATH.",
            err=True,
        )
        raise typer.Exit(code=2)
    env = dict(os.environ)
    settings = Settings.from_env()
    env.setdefault(
        "ROUTE_FORGE_URL", f"http://{settings.http_host}:{settings.http_port}"
    )
    raise typer.Exit(code=subprocess.run([str(binary)], env=env, check=False).returncode)


def locate_tui() -> Path | None:
    """PATH first, then the release build inside the repository."""
    on_path = shutil.which("routeforge-tui")
    if on_path:
        return Path(on_path)
    root = Path(__file__).resolve().parents[3]
    name = "routeforge-tui.exe" if sys.platform == "win32" else "routeforge-tui"
    candidate = root / "target" / "release" / name
    return candidate if candidate.exists() else None


@app.command()
def pool() -> None:
    """Print the rotation pool state as JSON."""
    import json

    with runtime_or_exit() as runtime:
        typer.echo(json.dumps(runtime.pool.snapshot(), indent=2, default=str))


if __name__ == "__main__":
    app()
