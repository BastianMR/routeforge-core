# Tasks — mcp-skill-hub-and-tui

Numbered checklist. Each item is verifiable.

## 1. Database schema

- [x] 1.1 Add migration for `plugins` table (idempotent CREATE IF NOT EXISTS)
- [x] 1.2 Add migration for `usage_log` new columns (`tags`, `provider_group`)
- [x] 1.3 Add migration for `usage_daily` rollup table
- [x] 1.4 Add indexes: `idx_usage_log_skill_time`, `idx_usage_log_account_time`
- [x] 1.5 `db.migrate()` runs all new migrations on startup, no-op when already current
- [x] 1.6 Test: `test_db_migration.py` — fresh DB creates all tables; existing DB with rows gets new columns without losing data

## 2. Account tags

- [x] 2.1 Extend `Account` Pydantic model with `tags: list[str] = []`
- [x] 2.2 Extend `AccountRepo` with `update_tags(account_id, tags)`, `list_by_tag(tag)`, `list_tags()`
- [x] 2.3 Extend `AccountCreate` (CLI) to accept `--tags` (comma-separated)
- [x] 2.4 Test: `test_account_tags.py` — CRUD on tags; `list_by_tag` returns expected subset

## 3. Skill provider_group

- [x] 3.1 Extend `SkillInfo` with `provider_group: str | None = None`
- [x] 3.2 Extend `Skill` ABC with property `info: SkillInfo` (already exists; ensure subclasses set `provider_group`)
- [x] 3.3 Test: `test_skill_provider_group.py` — Skill instances expose `info.provider_group`

## 4. Plugin discovery

- [x] 4.1 Create `src/routeforge/plugins/__init__.py` and `discovery.py`
- [x] 4.2 Implement `PluginManifest` Pydantic model with `module`, `attr`, `info` fields
- [x] 4.3 Implement `PluginDiscovery.scan(plugins_dir) -> list[Plugin]`
- [x] 4.4 Implement `PluginDiscovery.load(plugin) -> Skill` (importlib + getattr)
- [x] 4.5 Validate manifest: `name` not in builtin, module importable, attr is a `Skill` subclass
- [x] 4.6 Implement `PluginRepo` (CRUD on `plugins` table)
- [x] 4.7 On startup, registry reads `plugins` table and re-imports enabled plugins
- [x] 4.8 Test: `test_plugin_discovery.py` — valid manifest loads, invalid raises clear error, missing module marks `enabled=0`

## 5. Skills registry — reload

- [x] 5.1 Add `SkillRegistry.load_external(sources)` — calls `PluginDiscovery.scan` for each source dir
- [x] 5.2 Add `SkillRegistry.reload()` — clears, rescans, diffs, emits `skill.reloaded` event
- [x] 5.3 Add `SkillRegistry.source(skill_name) -> Literal["builtin", "plugin", "manifest"]`
- [x] 5.4 Update `SkillRegistry.list_all()` to include source metadata
- [x] 5.5 Test: `test_registry_reload.py` — adding/removing plugins updates the registry; existing skills unchanged

## 6. Rotation with tags

- [x] 6.1 Extend `RoundRobinPool.pick(accounts)` to take the (already filtered) candidate set; behavior unchanged for callers
- [x] 6.2 `RoundRobinPool.mark_failure` continues to short-circuit on 4xx except 402/429
- [x] 6.3 Add `RoundRobinPool.snapshot()` returning per-account `{state, cooldown_until, consecutive_failures, last_used_at}`
- [x] 6.4 Test: `test_rotation_tags.py` — pool with 3 tagged accounts rotates; cooldown excludes the right one

## 7. Routing with provider_group

- [x] 7.1 `Router.dispatch(skill_name, arguments)` resolves skill, then:
  - if `skill.info.provider_group`: filter accounts by tag intersection
  - else: existing behavior (filter by provider)
- [x] 7.2 Empty candidate set → raise `RouterError("no_accounts_for_group")`
- [x] 7.3 `_EphemeralAccount` (for `requires_account=False`) still bypasses the pool
- [x] 7.4 Test: `test_router_provider_group.py` — skill with `provider_group="scrape"` only sees tagged accounts; skill without group still works

## 8. Usage tracking

- [x] 8.1 Extend `UsageLogRepo.insert(event)` with the new columns
- [x] 8.2 `Router.dispatch` writes one row per call (after skill.execute returns, regardless of status)
- [x] 8.3 Add `UsageLogRepo.aggregate(window, group_by)` returning dicts for the API
- [x] 8.4 Add HTTP endpoint `GET /v1/usage?skill=&since=&group_by=`
- [x] 8.5 Background task `usage_rollup` runs every 5 minutes, fills `usage_daily`
- [x] 8.6 Test: `test_usage_tracking.py` — events are recorded; aggregations match manual counts

## 9. Event bus and SSE

- [x] 9.1 `src/routeforge/events/__init__.py` and `bus.py`
- [x] 9.2 `EventBus.publish(event)` and `EventBus.subscribe() -> asyncio.Queue`
- [x] 9.3 Ring buffer of last 100 events (configurable via `ROUTE_FORGE_EVENT_BUFFER_SIZE`)
- [x] 9.4 Emit `account.cooldown_started`, `account.recovered`, `account.disabled`, `skill.reloaded`, `usage.tick`, `call.completed`
- [x] 9.5 HTTP endpoint `GET /v1/events` (Server-Sent Events)
- [x] 9.6 Heartbeat every 15s
- [x] 9.7 CLI command `routeforge events` (tail SSE for debugging)
- [x] 9.8 Test: `test_event_bus.py` — subscriber receives published events; SSE endpoint streams text/event-stream

## 10. MCP server changes

- [x] 10.1 Declare `listChanged: true` in MCP capabilities
- [x] 10.2 On `SkillRegistry.reload()`, send `notifications/tools/list_changed` to all sessions
- [x] 10.3 New tool `reload_skills()` — calls `SkillRegistry.reload()`
- [x] 10.4 New tool `list_plugins()` — returns plugin list with source path
- [x] 10.5 New tool `tag_account(label, add, remove)` — manages tags
- [x] 10.6 Optional streamable-HTTP transport at `/mcp` (env `ROUTE_FORGE_MCP_HTTP_PORT`)
- [x] 10.7 Test: `test_mcp_list_changed.py` — reload emits notification; `tag_account` mutates and persists

## 11. CLI

- [x] 11.1 `src/routeforge/cli/skills.py` with `list`, `add`, `remove`, `reload` (Typer subcommands)
- [x] 11.2 `src/routeforge/cli/plugins.py` with `list`, `install <github-url>`
- [x] 11.3 Extend `src/routeforge/cli/accounts.py` with `tag <label> --add/--remove` and `untag <label> --remove`
- [x] 11.4 `src/routeforge/cli/events.py` with `events` (tails SSE)
- [x] 11.5 Register all in `src/routeforge/cli/main.py`
- [x] 11.6 `routeforge tui` launches the Rust binary (delegates to subprocess)
- [x] 11.7 Test: `test_cli_skills.py`, `test_cli_plugins.py`, `test_cli_accounts.py` using `typer.testing.CliRunner`

## 12. TUI workspace (Rust)

- [x] 12.1 Root `Cargo.toml` with `[workspace]` and members `["crates/*"]`
- [x] 12.2 Crate `crates/routeforge-tui/` with `Cargo.toml` (ratatui, crossterm, reqwest, tokio, serde, eventsource-stream, anyhow, chrono)
- [x] 12.3 `src/main.rs` — entry point, parse args, init `App`
- [x] 12.4 `src/app.rs` — top-level state + event loop (tick 250ms, repaint)
- [x] 12.5 `src/api/client.rs` — HTTP client (reqwest) for `GET /v1/accounts`, `/v1/skills`, `/v1/usage`, `POST` actions
- [x] 12.6 `src/api/events.rs` — SSE consumer using `eventsource-stream`
- [x] 12.7 `src/ui/mod.rs` and per-tab widgets: `accounts.rs`, `skills.rs`, `usage.rs`, `logs.rs`, `help.rs`
- [x] 12.8 `src/config.rs` — read `ROUTE_FORGE_URL` env (default `http://127.0.0.1:8787`)
- [ ] 12.9 `cargo build --release` produces `target/release/routeforge-tui.exe`
- [ ] 12.10 `cargo test` passes for any unit tests (pure logic, no UI rendering)

## 13. Documentation

- [x] 13.1 Update `README.md`: add TUI section with screenshots (ASCII), plugin discovery example, SSE endpoint table, MCP `listChanged` note
- [x] 13.2 Add a `README.md` in `crates/routeforge-tui/` documenting how to build and run
- [x] 13.3 Update `AGENTS.md` to mention the new specs (`skills-discovery`, `usage-tracking`, `tui`, `events`, `cli`) and the workspace layout
- [x] 13.4 Update `CHANGELOG.md` with a `[unreleased]` entry describing the change
- [x] 13.5 Add a small visual logo (SVG, ASCII fallback) to the README so it looks like the shiki-style polish we agreed on

## 14. CI

- [x] 14.1 `.github/workflows/ci.yml` adds a Rust toolchain step (`dtolnay/rust-toolchain@stable`) before the lint/test job
- [x] 14.2 CI runs `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` for the TUI
- [x] 14.3 `openspec validate mcp-skill-hub-and-tui` runs as before

## 15. Verification before archive

- [x] 15.1 `pytest -q` → all tests pass (Python)
- [ ] 15.2 `cargo test` → all tests pass (Rust)
- [x] 15.3 `ruff check src tests` → no issues
- [ ] 15.4 `cargo clippy -- -D warnings` → no issues
- [x] 15.5 `openspec validate mcp-skill-hub-and-tui` → valid
- [x] 15.6 Manual smoke: start `routeforge serve`, open `routeforge tui`, verify live SSE updates on cooldown/recovery
- [x] 15.7 Manual smoke: install a sample plugin, run `routeforge skills reload`, confirm `notifications/tools/list_changed` from a connected MCP client
