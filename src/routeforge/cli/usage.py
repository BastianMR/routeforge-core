"""`routeforge usage` commands."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import typer

from ..runtime import runtime_or_exit
from ..usage import parse_since

app = typer.Typer(help="Inspect and prune usage history")

_DURATION = re.compile(r"^(\d+)([smhdw])$")


@app.command("show")
def usage_show(
    provider: str | None = typer.Option(None, help="Filter by provider."),
    skill: str | None = typer.Option(None, help="Filter by skill name."),
    since: str | None = typer.Option(None, help="Window such as 1h, 24h, 7d."),
    group_by: str | None = typer.Option(None, help="account | skill"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    with runtime_or_exit() as runtime:
        if skill is not None or group_by is not None:
            if group_by is not None and group_by not in ("account", "skill"):
                typer.echo("error: group_by must be 'account' or 'skill'", err=True)
                raise typer.Exit(code=2)
            rows = runtime.usage.aggregate(since=parse_since(since), group_by=group_by)
            if skill is not None:
                rows = [r for r in rows if r.get("skill_name") == skill]
            typer.echo(json.dumps(rows, indent=2, default=str))
            return
        typer.echo(
            json.dumps(
                runtime.router.usage_summary(provider).model_dump(), indent=2, default=str
            )
        )


@app.command("prune")
def usage_prune(
    older_than: str = typer.Option(
        "90d", "--older-than", help="Delete usage_log rows older than this, e.g. 90d."
    ),
    daily_older_than: str = typer.Option(
        "365d", "--daily-older-than", help="Delete usage_daily rows older than this."
    ),
) -> None:
    """Delete usage rows past the retention window, in a single transaction."""
    log_cutoff = _parse_duration(older_than)
    daily_cutoff = _parse_duration(daily_older_than)
    if log_cutoff is None or daily_cutoff is None:
        typer.echo("error: durations look like 90d, 12h, 30m, 1w", err=True)
        raise typer.Exit(code=2)
    with runtime_or_exit() as runtime:
        removed = runtime.usage.prune(log_cutoff)
        with runtime.conn:
            cursor = runtime.conn.execute(
                "DELETE FROM usage_daily WHERE day < ?",
                (daily_cutoff.strftime("%Y-%m-%d"),),
            )
        daily_removed = cursor.rowcount or 0
        typer.echo(f"deleted {removed} usage_log row(s) older than {older_than}")
        typer.echo(f"deleted {daily_removed} usage_daily row(s) older than {daily_older_than}")


def _parse_duration(value: str) -> datetime | None:
    match = _DURATION.match(value.strip().lower())
    if match is None:
        return None
    amount = int(match.group(1))
    delta = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }[match.group(2)]
    return datetime.now(UTC).replace(tzinfo=None) - delta
