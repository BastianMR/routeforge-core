# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `mcp` was declared as `>=1.0` with no upper bound while the server targets the
  1.x SDK. A fresh install resolved `mcp` 2.x, where `FastMCP` was renamed to
  `MCPServer`, and every `routeforge mcp` invocation plus the test suite failed
  to import. Pinned to `mcp>=1.0,<2` until the port is done.
- CI validated `openspec validate bootstrap-core`, a change that had already
  been archived, so the step always failed. It now runs
  `openspec validate --all --strict` plus `--archived --strict` and never
  hardcodes a change name.
- The TUI's `notifications/tools/list_changed` was emitted on the event bus but
  never reached MCP clients: `send_tool_list_changed` lives on `ServerSession`
  and is only reachable through the request ContextVar. `reload_skills` is now
  async and notifies from inside the tool call.
- In the TUI, `r`, `space`, and `d` returned actions the main loop discarded,
  so none of the mutating keys did anything, and SSE reconnects resumed from
  event 0 and replayed the whole ring buffer.
- AGENTS.md cited a `process` capability and a `routing-schema` spec that do
  not exist.

### Added

- **Plugin skills** (`skills-discovery`). Skills load from `.toml` manifests
  in `~/.routeforge/plugins/` (`ROUTE_FORGE_PLUGINS_DIR`). Loaded plugins are
  persisted in a new `plugins` table and re-imported on restart; a module that
  fails to import is stored as `enabled=0` with the error on the row instead
  of crashing startup. Discovery makes no network calls; only
  `routeforge plugins install <github-url>` fetches anything, and it requires
  `--yes`.
- **Provider groups** (`rotation`, `routing`). `Account.tags` and
  `Skill.provider_group` let a skill rotate across accounts from different
  providers. `RoundRobinPool.pick(candidates)` now takes the already-filtered
  candidate set, so tags stay a routing concern. No tagged account yields
  `RouterError("no_accounts_for_group")` / HTTP 400.
- **Account enabled flag.** `Account.enabled` defaults to `true`;
  `POST /v1/accounts/manage/{toggle,disable}` flips it without deleting the
  account, and a disabled account is skipped like a cooled one.
- **Usage tracking** (`usage-tracking`). Every dispatch writes a `usage_log`
  row with `skill_name`, `status` (`success`, `error_4xx`, `error_5xx`,
  `error_network`), `latency_ms`, `provider_group`, `tags`, and `error`.
  `GET /v1/usage` supports `skill=`, `since=`, and `group_by=account|skill`.
  A background task rolls rows into `usage_daily` every 5 minutes, and
  `routeforge usage prune` applies retention.
- **Event bus** (`events`). In-process asyncio pub/sub with a 100-event ring
  buffer (`ROUTE_FORGE_EVENT_BUFFER_SIZE`) publishing `account.cooldown_started`,
  `account.recovered`, `account.disabled`, `skill.reloaded`, `usage.tick`, and
  `call.completed`.
- **SSE endpoint.** `GET /v1/events` streams those events as
  `text/event-stream` with 15s keepalive comments and `Last-Event-ID` replay.
- **Registry reload** (`skills-registry`). `SkillRegistry.reload()` re-scans
  every source and returns `{added, removed, updated}`.
- **Rust TUI** (`tui`). Cargo workspace at the root with
  `crates/routeforge-tui/`: ratatui client with Accounts, Skills, Usage, and
  Logs tabs, live updates over SSE, mutations over HTTP, and no direct SQLite
  access.
- **CLI** (`cli`). `routeforge skills`, `plugins`, `events`, `usage`, `pool`,
  and `accounts tag|untag|enable|disable|tags`, plus `--json` output and
  `routeforge tui` to launch the Rust binary.
- **MCP server.** Three new tools (`reload_skills`, `list_plugins`,
  `tag_account`) for a total of seven, plus `account_label` pinning on
  `call_skill`. Declares `capabilities.tools.listChanged = true` and sends
  `notifications/tools/list_changed` on reload. Optional streamable-HTTP
  transport at `/mcp` behind `ROUTE_FORGE_MCP_HTTP_PORT`, with optional
  `ROUTE_FORGE_MCP_HTTP_TOKEN` bearer auth.
- **New HTTP endpoints**: `GET /v1/accounts/pool`, `GET /v1/plugins`,
  `GET/POST /v1/skills/manage`, `POST /v1/accounts/manage/{toggle,disable,tags}`,
  `GET /v1/events`.

### Changed

- Default HTTP bind moved from `127.0.0.1:8080` to `127.0.0.1:8787`, matching
  the TUI default and the `routing` spec.
- `usage_log` columns renamed to match the spec: `skill` → `skill_name` and
  `status_code` → `status`. A startup migration adds the new columns and
  backfills existing rows, so old data is preserved.
- `skills-registry` tracks each skill's `source` (`builtin`, `plugin`,
  `manifest`) and exposes it through `GET /v1/skills`, `list_skills`, and
  `routeforge skills list --source`.
- `accounts add` accepts `--tags`.
- CI no longer hardcodes a change name: it runs `openspec validate --all
  --strict` plus `openspec validate --archived --strict`, and a new job runs
  `cargo fmt`, `cargo clippy`, and `cargo test` for the TUI.

### Migration

- `db.migrate()` runs on every startup and is idempotent. Databases created by
  `bootstrap-core` gain `accounts.tags`, `accounts.enabled`, the new
  `usage_log` columns, and the `plugins` / `usage_daily` tables without losing
  rows.
- Move from `ROUTE_FORGE_PORT=8080` to the new `8787` default, or keep the
  old port explicitly.

## [2026-09-25] - bootstrap-core

### Added

- OpenSpec spec-driven workflow: `openspec/` directory,
  `.opencode/commands/opsx-*.md`, `.opencode/skills/openspec-*/SKILL.md`.
- Five new capabilities under `openspec/specs/`:
  - `process` — how every change to this repo must be made.
  - `routing-schema` — request/response shapes for HTTP endpoints.
  - `rotation` — round-robin account pool with cooldown rules.
  - `secrets` — Fernet encryption of API keys at rest.
  - `skills-registry` — skill discovery and execution contract.
  - `mcp-server` — stdio MCP server with `list_skills`, `call_skill`,
    `list_accounts`, `get_usage`.
- Python package `routeforge` (Python 3.12, FastAPI, httpx, Typer,
  Pydantic, cryptography, mcp).
- Two builtin skills: `echo` and `firecrawl/scrape`.
- SQLite-backed account store with Fernet-encrypted API keys.
- Round-robin rotation pool with cooldown on 429/402/5xx and per-provider
  `cooldown_seconds` override.
- FastAPI HTTP server (`routeforge serve`) with
  `GET /v1/skills`, `POST /skills/{name}/call`,
  `POST /v1/chat/completions` (OpenAI-compatible with `skill:` prefix),
  `GET /v1/accounts`, `GET /v1/usage`.
- Typer CLI (`routeforge accounts add|list`, `routeforge secrets generate`).
- stdio MCP server (`routeforge mcp`).
- GitHub Actions CI: ruff + pytest + openspec validate.
- 19 unit tests covering secrets, rotation, router, skills.

### Changed

- README rewritten to describe the OpenSpec-first gateway.
- AGENTS rewritten to point at OpenSpec workflow.

### Migration

- `~/.routeforge/routeforge.db` is created on first run; back it up.
- `ROUTE_FORGE_MASTER_KEY` is required at startup; generate with
  `routeforge secrets generate`.