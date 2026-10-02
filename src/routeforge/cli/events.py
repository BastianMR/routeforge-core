"""`routeforge events` — tail the SSE stream for debugging."""

from __future__ import annotations

import json

import httpx
import typer

from ..config import Settings

app = typer.Typer(help="Observe the live event stream")


@app.callback(invoke_without_command=True)
def events(
    url: str | None = typer.Option(None, help="Override the core URL."),
    limit: int = typer.Option(0, help="Stop after N events. 0 means never."),
) -> None:
    """Print one JSON line per event until interrupted."""
    settings = Settings.from_env()
    base = (url or _default_url(settings)).rstrip("/")
    typer.echo(f"tailing {base}/v1/events (ctrl+c to stop)")
    seen = 0
    try:
        with httpx.stream("GET", f"{base}/v1/events", timeout=None) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                try:
                    typer.echo(json.dumps(json.loads(payload), sort_keys=True))
                except json.JSONDecodeError:
                    typer.echo(payload)
                seen += 1
                if limit and seen >= limit:
                    return
    except httpx.HTTPError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("stopped")


def _default_url(settings: Settings) -> str:
    return f"http://{settings.http_host}:{settings.http_port}"
