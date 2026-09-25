"""Typer CLI for routeforge-core."""

from __future__ import annotations

import httpx
import typer

from ..accounts import AccountRepo
from ..config import Settings
from ..db import connect
from ..rotation import RoundRobinPool
from ..router import Router
from ..secrets import Secrets
from ..skills.registry import SkillRegistry

app = typer.Typer(help="routeforge-core CLI")
accounts_app = typer.Typer(help="Manage provider accounts")
secrets_app = typer.Typer(help="Manage encryption")
app.add_typer(accounts_app, name="accounts")
app.add_typer(secrets_app, name="secrets")


def _open_repo() -> tuple[Settings, AccountRepo, Secrets]:
    settings = Settings.from_env()
    if not settings.master_key:
        typer.echo("error: ROUTE_FORGE_MASTER_KEY is required", err=True)
        raise typer.Exit(code=3)
    secrets = Secrets(settings.master_key)
    conn = connect(settings.db_path)
    repo = AccountRepo(conn, secrets)
    return settings, repo, secrets  # type: ignore[return-value]


@accounts_app.command("add")
def accounts_add(
    provider: str = typer.Option(..., help="Provider slug (e.g. firecrawl)."),
    label: str = typer.Option(..., help="Human-readable label for this account."),
    key: str = typer.Option(..., help="API key (will be encrypted at rest)."),
    base_url: str | None = typer.Option(None, help="Override upstream base URL."),
) -> None:
    _, repo, _ = _open_repo()
    account = repo.add(provider=provider, label=label, api_key=key, base_url=base_url)
    typer.echo(f"added account #{account.id}: {provider}/{label}")


@accounts_app.command("list")
def accounts_list(provider: str | None = typer.Option(None, help="Filter by provider.")) -> None:
    _, repo, _ = _open_repo()
    for info in repo.list_all():
        if provider is not None and info.provider != provider:
            continue
        typer.echo(
            f"{info.provider}/{info.label} (id={info.id}) last_used={info.last_used_at}"
        )


@secrets_app.command("generate")
def secrets_generate() -> None:
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
    if host or port:
        settings = Settings(
            db_path=settings.db_path,
            master_key=settings.master_key,
            http_host=host or settings.http_host,
            http_port=port or settings.http_port,
            allow_public=settings.allow_public,
            default_cooldown_seconds=settings.default_cooldown_seconds,
        )
    _validate_bind(settings)
    if not settings.master_key:
        typer.echo("error: ROUTE_FORGE_MASTER_KEY is required", err=True)
        raise typer.Exit(code=3)
    secrets = Secrets(settings.master_key)
    conn = connect(settings.db_path)
    repo = AccountRepo(conn, secrets)
    registry = SkillRegistry()
    registry.discover_builtin()
    pool = RoundRobinPool(repo, default_cooldown_seconds=settings.default_cooldown_seconds)
    http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    router = Router(repo, pool, registry, http, conn)
    api = create_app(router)
    uvicorn.run(api, host=settings.http_host, port=settings.http_port, log_level="info")


@app.command()
def mcp() -> None:
    """Run the MCP server over stdio."""
    settings = Settings.from_env()
    if not settings.master_key:
        typer.echo("error: ROUTE_FORGE_MASTER_KEY is required", err=True)
        raise typer.Exit(code=3)
    secrets = Secrets(settings.master_key)
    conn = connect(settings.db_path)
    repo = AccountRepo(conn, secrets)
    registry = SkillRegistry()
    registry.discover_builtin()
    pool = RoundRobinPool(repo, default_cooldown_seconds=settings.default_cooldown_seconds)
    http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    router = Router(repo, pool, registry, http, conn)
    from ..mcp_server import build_server

    server = build_server(router)
    server.run(transport="stdio")


if __name__ == "__main__":
    app()
