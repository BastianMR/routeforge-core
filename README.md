# routeforge-core

Multi-account AI API gateway. Rotate N keys per provider, dispatch skill
calls to the upstream API, expose the whole thing as OpenAI-compatible HTTP
and as an MCP server so any AI agent (Claude Code, Cursor, opencode, ...)
can discover and call your skills without per-tool configuration.

```
[any MCP-aware agent]  --stdio-->  routeforge mcp   (skills, accounts, usage)
[curl / OpenAI client] --http-->  routeforge serve (OpenAI-compat + typed endpoints)
                                       |
                                       v
                              RoundRobinPool  --->  firecrawl / tavily / exa / ...
                              (cooldown on 429/402/5xx)
```

## Features

- **Multi-account rotation** — round-robin with automatic cooldown when an
  upstream returns 429, 402, or 5xx.
- **Encrypted secrets** — every API key lives in SQLite, encrypted with
  Fernet (AES-128-CBC + HMAC-SHA256) under a master key you supply via env.
- **Pluggable skills** — drop a class subclassing `Skill` into
  `routeforge/skills/builtin/` and it is discovered at startup.
- **OpenAI-compatible HTTP** — `POST /v1/chat/completions` with
  `model: "skill:<name>"` plus `POST /skills/<name>/call`.
- **MCP server (stdio)** — exposes `list_skills`, `call_skill`,
  `list_accounts`, `get_usage` to any MCP-compatible client.
- **Local-first** — defaults to `127.0.0.1:8080`; refuses to bind to a
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
routeforge accounts add --provider firecrawl --label personal-1 --key fc-xxx
routeforge accounts add --provider firecrawl --label personal-2 --key fc-yyy
routeforge accounts add --provider firecrawl --label personal-3 --key fc-zzz

# 3a. Run the HTTP server
routeforge serve
# -> http://127.0.0.1:8080

# 3b. Or run the MCP server over stdio (for Claude Code, Cursor, opencode, etc.)
routeforge mcp
```

## HTTP API

```bash
# List registered skills
curl http://127.0.0.1:8080/v1/skills

# Call a skill directly
curl -X POST http://127.0.0.1:8080/skills/echo/call \
  -H 'Content-Type: application/json' \
  -d '{"args": {"hello": "world"}}'

# OpenAI-compatible call
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"skill:echo","messages":[{"role":"user","content":"hi"}]}'

# Inspect accounts (no secrets leaked)
curl http://127.0.0.1:8080/v1/accounts

# Aggregated usage
curl 'http://127.0.0.1:8080/v1/usage?provider=firecrawl'
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

Four tools are exposed:

- `list_skills()` — every registered skill with name, provider, description, schema.
- `call_skill(name, args)` — execute a skill; returns `{result, account_id, latency_ms}` or `{error}`.
- `list_accounts(provider=None)` — metadata only (no API keys).
- `get_usage(provider=None)` — call counts and error rates by skill and account.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `ROUTE_FORGE_MASTER_KEY` | (required) | Fernet key for encrypting API keys at rest. |
| `ROUTE_FORGE_DB` | `~/.routeforge/routeforge.db` | SQLite database path. |
| `ROUTE_FORGE_HOST` | `127.0.0.1` | HTTP bind host. |
| `ROUTE_FORGE_PORT` | `8080` | HTTP bind port. |
| `ROUTE_FORGE_ALLOW_PUBLIC` | `0` | Set to `1` to bind to a non-loopback address. |
| `ROUTE_FORGE_COOLDOWN` | `60` | Default cooldown seconds on upstream 429/402/5xx. |

## Process

This repository follows the OpenSpec spec-driven workflow. Every change
starts in `openspec/changes/<name>/` and ends in `openspec/specs/` after
archive. See `AGENTS.md` and `openspec/specs/process/spec.md` (post-archive).

## License

MIT — see `LICENSE`.