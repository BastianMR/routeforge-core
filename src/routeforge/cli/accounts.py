"""`routeforge accounts` commands."""

from __future__ import annotations

import json

import typer

from ..runtime import runtime_or_exit

app = typer.Typer(help="Manage provider accounts")


def _resolve(runtime, label: str):
    account = runtime.repo.get_by_label(label)
    if account is None:
        typer.echo(f"error: account not found: {label}", err=True)
        raise typer.Exit(code=4)
    return account


@app.command("add")
def accounts_add(
    provider: str = typer.Option(..., help="Provider slug (e.g. firecrawl)."),
    label: str = typer.Option(..., help="Human-readable label for this account."),
    key: str = typer.Option(..., help="API key (will be encrypted at rest)."),
    base_url: str | None = typer.Option(None, help="Override upstream base URL."),
    tags: str | None = typer.Option(None, help="Comma-separated tags, e.g. scrape,web."),
) -> None:
    with runtime_or_exit() as runtime:
        account = runtime.repo.add(
            provider=provider,
            label=label,
            api_key=key,
            base_url=base_url,
            tags=tags,
        )
        typer.echo(f"added account #{account.id}: {provider}/{label}")
        if account.tags:
            typer.echo(f"tags: {', '.join(account.tags)}")


@app.command("list")
def accounts_list(
    provider: str | None = typer.Option(None, help="Filter by provider."),
    tag: str | None = typer.Option(None, help="Filter by tag."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
) -> None:
    with runtime_or_exit() as runtime:
        rows = [
            info.model_dump()
            for info in runtime.repo.list_all()
            if (provider is None or info.provider == provider)
            and (tag is None or tag in info.tags)
        ]
        if as_json:
            typer.echo(json.dumps(rows, indent=2, default=str))
            return
        if not rows:
            typer.echo("(no accounts)")
            return
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled"
            tags = ",".join(row["tags"]) or "-"
            typer.echo(
                f"{row['provider']}/{row['label']} (id={row['id']}) "
                f"{state} tags={tags} last_used={row['last_used_at']}"
            )


@app.command("tag")
def accounts_tag(
    label: str = typer.Argument(..., help="Account label."),
    add: str | None = typer.Option(None, help="Comma-separated tags to add."),
    remove: str | None = typer.Option(None, help="Comma-separated tags to remove."),
) -> None:
    """Add and/or remove tags on an account."""
    if not add and not remove:
        typer.echo("error: pass --add and/or --remove", err=True)
        raise typer.Exit(code=2)
    with runtime_or_exit() as runtime:
        account = _resolve(runtime, label)
        tags = runtime.repo.add_tags(account.id, add)
        if remove:
            tags = runtime.repo.remove_tags(account.id, remove)
        typer.echo(f"{label} tags: {', '.join(tags) if tags else '(none)'}")


@app.command("untag")
def accounts_untag(
    label: str = typer.Argument(..., help="Account label."),
    remove: str = typer.Option(..., "--remove", help="Comma-separated tags to remove."),
) -> None:
    """Remove tags from an account."""
    with runtime_or_exit() as runtime:
        account = _resolve(runtime, label)
        tags = runtime.repo.remove_tags(account.id, remove)
        typer.echo(f"{label} tags: {', '.join(tags) if tags else '(none)'}")


@app.command("enable")
def accounts_enable(
    label: str = typer.Argument(..., help="Account label."),
) -> None:
    with runtime_or_exit() as runtime:
        account = _resolve(runtime, label)
        runtime.repo.set_enabled(account.id, True)
        typer.echo(f"{label} enabled")


@app.command("disable")
def accounts_disable(
    label: str = typer.Argument(..., help="Account label."),
) -> None:
    with runtime_or_exit() as runtime:
        account = _resolve(runtime, label)
        runtime.repo.set_enabled(account.id, False)
        typer.echo(f"{label} disabled")


@app.command("tags")
def accounts_tags() -> None:
    """List every distinct tag across all accounts."""
    with runtime_or_exit() as runtime:
        tags = runtime.repo.list_tags()
        typer.echo("\n".join(tags) if tags else "(no tags)")
