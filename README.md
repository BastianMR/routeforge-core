# routeforge-core

<img src="docs/logo.svg" alt="routeforge" width="240">

```
      o            o   o
      |          /   o   \
      o--->  (o) --> (o) --> o
```

Multi-account AI API gateway. Rotate N keys per provider, dispatch skill
calls to the upstream API, expose the whole thing as OpenAI-compatible HTTP
and as an MCP server so any AI agent (Claude Code, Cursor, opencode, ...)
can discover and call your skills without per-tool configuration.

```
[any MCP-aware agent]  --stdio-->  routeforge mcp   (skills, accounts, usage)
[curl / OpenAI client] --http-->  routeforge serve (OpenAI-compat + typed endpoints)
[TUI]                  --http+SSE-> routeforge serve (live state, no polling)
                                       |
                                       v
                              RoundRobinPool  --->  firecrawl / tavily / exa / ...
                              (cooldown on 429/402/5xx)
```

## Features

- **Multi-account rotation** — round-robin with automatic cooldown when an
  upstream returns 429, 402, or 5xx.
- **Provider groups** — tag accounts (`scrape`) and point a skill at the tag,
  so three keys from firecrawl, tavily, and exa rotate as one pool.
- **Plugin skills** — drop a `.toml` manifest in `~/.routeforge/plugins/` and
  the skill is discovered at startup; no reinstall, no source edit.
- **Encrypted secrets** — every API key lives in SQLite, encrypted with
  Fernet (AES-128-CBC + HMAC-SHA256) under a master key you supply via env.
- **Pluggable skills** — drop a class subclassing `Skill` into
  `routeforge/skills/builtin/` and it is discovered at startup.
- **OpenAI-compatible HTTP** — `POST /v1/chat/completions` with
  `model: "skill:<name>"` plus `POST /skills/<name>/call`.
- **MCP server (stdio)** — exposes seven tools to any MCP-compatible client,
  and advertises `listChanged` so agents see plugin reloads live.
- **Live event stream** — `GET /v1/events` (SSE) for cooldowns, recoveries,
  reloads, and call completions.
- **Terminal UI** — `routeforge tui`, a Rust binary with Accounts, Skills,
  Usage, and Logs tabs.
- **Local-first** — defaults to `127.0.0.1:8787`; refuses to bind to a
  public address unless `ROUTE_FORGE_ALLOW_PUBLIC=1`.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.12+.

## Quick start

```bash
# 1. Generate a master encryption key
export ROUTE_FORGE_MASTER_KEY=$(routeforge secrets generate)

# 2. Add one or more accounts per provider
routeforge accounts add --provider firecrawl --label personal-1 --key fc-xxx --tags scrape
routeforge accounts add --provider firecrawl --label personal-2 --key fc-yyy --tags scrape
routeforge accounts add --provider firecrawl --label personal-3 --key fc-zzz --tags scrape

# 3a. Run the HTTP server
routeforge serve
# -> http://127.0.0.1:8787

# 3b. Or run the MCP server over stdio (for Claude Code, Cursor, opencode, etc.)
routeforge mcp

# 3c. Or watch it live from a terminal
routeforge tui
```

## HTTP API

```bash
# List registered skills
curl http://127.0.0.1:8787/v1/skills

# Call a skill directly
curl -X POST http://127.0.0.1:8787/skills/echo/call \
  -H 'Content-Type: application/json' \
  -d '{"args": {"hello": "world"}}'

# OpenAI-compatible call
curl -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"skill:echo","messages":[{"role":"user","content":"hi"}]}'

# Inspect accounts (no secrets leaked)
curl http://127.0.0.1:8787/v1/accounts

# Rotation pool state, as the TUI renders it
curl http://127.0.0.1:8787/v1/accounts/pool

# Aggregated usage
curl 'http://127.0.0.1:8787/v1/usage?provider=firecrawl'
curl 'http://127.0.0.1:8787/v1/usage?group_by=skill&since=24h'
curl 'http://127.0.0.1:8787/v1/usage?skill=echo&since=1h'
```

### Endpoint reference

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/skills` | Every skill with `source`, `provider_group`, `requires_account`, `schema`. |
| `GET` | `/v1/skills/manage?source=` | Skills with their plugin manifest and module paths. |
| `POST` | `/v1/skills/manage/reload` | Re-scan all sources; returns `{added, removed, updated}`. |
| `GET` | `/v1/plugins` | Plugin rows with `enabled`, `error`, `loaded_at`. |
| `POST` | `/skills/{name}/call` | `{args}` in, skill output out. |
| `POST` | `/v1/chat/completions` | OpenAI-shaped; route with `model: "skill:<name>"`. |
| `GET` | `/v1/accounts` | Accounts grouped by provider, with `tags` and `enabled`. |
| `GET` | `/v1/accounts/pool` | Per-account `{state, cooldown_until, consecutive_failures}`. |
| `POST` | `/v1/accounts/manage/toggle` | Invert the `enabled` flag. |
| `POST` | `/v1/accounts/manage/disable` | Set `enabled=false`. |
| `POST` | `/v1/accounts/manage/tags` | Add or remove tags by `account_id`. |
| `GET` | `/v1/usage?provider=` | Legacy `{provider, calls, errors, by_account, by_skill}`. |
| `GET` | `/v1/usage?skill=&since=` | Raw usage rows for one skill (capped at 1000). |
| `GET` | `/v1/usage?group_by=account\|skill` | Aggregated counts and latency. |
| `GET` | `/v1/events` | SSE stream; `Last-Event-ID` replays from the ring buffer. |

### Live events

`GET /v1/events` is a `text/event-stream`. Each frame is one JSON payload under
`data:`, tagged with an `event:` name and a monotonic `id:`. A `: keepalive`
comment is sent every 15 seconds so proxies keep the connection open.

```
event: account.cooldown_started
id: 42
data: {"account_id": 5, "until": "2026-09-25T12:34:56Z", "reason": "429", "ts": "..."}
```

| Event | Payload |
|-------|---------|
| `account.cooldown_started` | `{account_id, until, reason}` |
| `account.recovered` | `{account_id}` |
| `account.disabled` | `{account_id}` |
| `skill.reloaded` | `{added, removed, updated}` |
| `usage.tick` | `{window, requests, errors, ts}` |
| `call.completed` | `{skill, account_id, status, latency_ms, ts}` |

The bus keeps the last 100 events in a ring buffer
(`ROUTE_FORGE_EVENT_BUFFER_SIZE`) so a reconnecting client can replay with
`Last-Event-ID`. A subscriber that falls behind drops events and the drop is
counted; the core never blocks on a slow client.

```bash
# Tail the stream from the terminal
routeforge events
```

## Built-in skills

| Skill | Provider | Notes |
|-------|----------|-------|
| `echo` | `echo` | Returns args unchanged. Useful for smoke tests; requires no account. |
| `firecrawl/scrape` | `firecrawl` | POSTs `{url, formats}` to the upstream `/v1/scrape`. |

## Adding your own skill

```python
# src/routeforge/skills/builtin/myprovider.py
from typing import Any
import httpx
from ..base import Skill
from ...models import Account, SkillSchemaModel


class MyProviderSearchSkill(Skill):
    name = "myprovider/search"
    provider = "myprovider"
    description = "Call the myprovider search API."

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel(
            inputs={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
            outputs={"type": "object"},
        )

    async def execute(self, account: Account, args: dict[str, Any], http: httpx.AsyncClient) -> dict[str, Any]:
        r = await http.post(
            "https://api.myprovider.com/search",
            json={"q": args["q"]},
            headers={"Authorization": f"Bearer {account.api_key}"},
        )
        r.raise_for_status()
        return r.json()
```

Restart `routeforge serve` / `routeforge mcp` to pick it up.

## Plugin skills

A builtin skill requires editing the source tree and reinstalling. A plugin
skill does not: drop a manifest in `~/.routeforge/plugins/` and reload.

```toml
# ~/.routeforge/plugins/web-scrape.toml
module = "my_skills.scraper"
attr = "WebScrapeSkill"

[info]
name = "web-scrape"
description = "Scrape via any provider tagged 'scrape'."
requires_account = true
provider_group = "scrape"
```

The module is resolved against `sys.path`; `routeforge` never runs `pip
install` for you. Then:

```bash
# Load it now, without restarting
routeforge skills add --from-toml ~/.routeforge/plugins/web-scrape.toml

# Or re-scan every source
routeforge skills reload

# Inspect what is loaded, and why something is not
routeforge skills list --source plugin
routeforge plugins list

# Clone a repo of skills from GitHub (asks for --yes)
routeforge plugins install https://github.com/me/my-skills --yes
```

Loaded plugins are persisted in the `plugins` SQLite table, so a restart
re-imports them without touching the manifest again. A plugin whose module
fails to import is marked `enabled=0` with the error stored on the row — it
never blocks startup, and `routeforge plugins list` shows why.

Plugins execute arbitrary Python. Discovery makes no network calls; only the
explicit `plugins install` command fetches anything, and it echoes the URL and
requires `--yes`.

### Provider groups

`provider_group` is what makes cross-provider rotation work. Tag the accounts
you consider interchangeable, then point a skill at the tag instead of a single
provider:

```bash
routeforge accounts add --provider firecrawl --label fc1 --key fc-xxx --tags scrape
routeforge accounts add --provider tavily    --label tv1 --key tv-yyy --tags scrape
routeforge accounts add --provider exa       --label ex1 --key ex-zzz --tags scrape
```

A skill declaring `provider_group = "scrape"` now rotates across all three,
cooldown included. A skill with no group keeps the original one-provider
behavior. When no account carries the tag, the call returns HTTP 400 with
`{"error": "no_accounts_for_group", "skill": ..., "group": ...}`.

## TUI

```bash
cargo build --release --manifest-path crates/routeforge-tui/Cargo.toml
routeforge serve    # terminal 1
routeforge tui      # terminal 2
```

```
┌─ routeforge ─────────────────────────────────────────────────────────┐
│ [1] Accounts  [2] Skills  [3] Usage  [4] Logs                         │
├───────────────────────────────────────────────────────────────────────┤
│ OK  fc1   firecrawl  scrape,web   active          2026-09-25 12:00:01 │
│ ..  tv1   tavily     scrape       cooldown  42s   2026-09-25 11:58:44 │
│ XX  ex1   exa        search       disabled         -                  │
├───────────────────────────────────────────────────────────────────────┤
│ 124 calls/min  2 in cooldown  3 err/min  live  ·  /  ·  q quit       │
└───────────────────────────────────────────────────────────────────────┘
```

Four tabs, `1`..`4` to switch, `/` to filter, `r` to reload skills, `space` to
toggle an account, `d` to disable it, `q` to quit. Rows update straight from
the SSE stream, so a cooldown shows up without a refresh. The TUI never opens
the database: it reads the HTTP API and writes only through `POST`. Point it at
another host with `ROUTE_FORGE_URL`. See `crates/routeforge-tui/README.md`.

## MCP integration

Add the server to any MCP client that supports stdio:

```json
{
  "mcpServers": {
    "routeforge": {
      "command": "routeforge",
      "args": ["mcp"],
      "env": {
        "ROUTE_FORGE_MASTER_KEY": "<your-fernet-key>"
      }
    }
  }
}
```

Seven tools are exposed:

- `list_skills()` — every registered skill with name, source, provider,
  description, schema, `provider_group`, and `requires_account`.
- `call_skill(name, args, account_label=None)` — execute a skill; returns
  `{result, account_id, latency_ms}` or `{error, isError}`. Pinning
  `account_label` bypasses round-robin.
- `list_accounts(provider=None)` — metadata only (no API keys), including
  `tags` and `enabled`.
- `get_usage(provider=None)` — call counts and error rates by skill and account.
- `reload_skills()` — re-scan every source; returns `{added, removed, updated}`.
- `list_plugins()` — loaded plugins with manifest path, module, and state.
- `tag_account(label, add=None, remove=None)` — manage an account's tags.

The server declares `capabilities.tools.listChanged = true`, so a reload
pushes `notifications/tools/list_changed` to every connected session and the
agent refreshes its tool list without polling.

An optional streamable-HTTP transport is available at `/mcp` when
`ROUTE_FORGE_MCP_HTTP_PORT` is set; add `ROUTE_FORGE_MCP_HTTP_TOKEN` to require
a bearer token. Without it, only stdio is available and no TCP port is bound.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `ROUTE_FORGE_MASTER_KEY` | (required) | Fernet key for encrypting API keys at rest. |
| `ROUTE_FORGE_DB` | `~/.routeforge/routeforge.db` | SQLite database path. |
| `ROUTE_FORGE_HOST` | `127.0.0.1` | HTTP bind host. |
| `ROUTE_FORGE_PORT` | `8787` | HTTP bind port. |
| `ROUTE_FORGE_ALLOW_PUBLIC` | `0` | Set to `1` to bind to a non-loopback address. |
| `ROUTE_FORGE_COOLDOWN` | `60` | Default cooldown seconds on upstream 429/402/5xx. |
| `ROUTE_FORGE_PLUGINS_DIR` | `~/.routeforge/plugins` | Where plugin manifests are scanned. |
| `ROUTE_FORGE_MANIFEST_PATH` | (unset) | Optional declarative YAML manifest, reserved for v2. |
| `ROUTE_FORGE_EVENT_BUFFER_SIZE` | `100` | SSE ring buffer size for replay. |
| `ROUTE_FORGE_SSE_HEARTBEAT_SECONDS` | `15` | Keepalive comment interval. |
| `ROUTE_FORGE_USAGE_ROLLUP_SECONDS` | `300` | `usage_daily` rollup interval. |
| `ROUTE_FORGE_USAGE_TICK_SECONDS` | `60` | `usage.tick` event interval. |
| `ROUTE_FORGE_MCP_HTTP_PORT` | (unset) | Enables the streamable-HTTP MCP transport. |
| `ROUTE_FORGE_MCP_HTTP_TOKEN` | (unset) | Bearer token for the HTTP MCP transport. |
| `ROUTE_FORGE_URL` | `http://127.0.0.1:8787` | Core URL, read by the TUI. |

## CLI

```bash
routeforge secrets generate                     # fresh master key
routeforge accounts add|list|enable|disable|tags
routeforge accounts tag fc1 --add scrape,web
routeforge accounts untag fc1 --remove scrape
routeforge skills list|add|remove|reload
routeforge plugins list|install
routeforge usage show|prune
routeforge events                               # tail SSE
routeforge pool                                 # pool state as JSON
routeforge serve | mcp | tui
```

Add `--json` to `accounts list`, `skills list`, `plugins list`, and `usage show`
for machine-readable output.

## Process

This repository follows the OpenSpec spec-driven workflow. Every change
starts in `openspec/changes/<name>/` and ends in `openspec/specs/` after
archive. See `AGENTS.md` for the operating rules and `openspec/specs/` for the
live capabilities.

```bash
ruff check src tests
pytest -q
openspec validate --all --strict
openspec validate --archived --strict
cargo test --manifest-path crates/routeforge-tui/Cargo.toml
```

## License

MIT — see `LICENSE`.