# Design — mcp-skill-hub-and-tui

## Architecture

```
┌──────────────────────────┐        ┌──────────────────────────┐
│  MCP clients             │        │  HTTP clients            │
│  (Claude Desktop, Code,  │        │  (OpenAI-compat, custom) │
│   Cursor, Continue)      │        │                          │
└──────────┬───────────────┘        └──────────┬───────────────┘
           │ stdio / streamable-HTTP          │ HTTP/JSON
           ▼                                  ▼
┌──────────────────────────────────────────────────────────────┐
│                    routeforge-core (Python)                  │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ FastAPI  │  │   MCP    │  │   CLI    │  │  Event Bus   │ │
│  │   app    │  │  server  │  │ (typer)  │  │  (asyncio)   │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘ │
│       │              │              │              │         │
│       └──────────────┴──────┬───────┴──────────────┘         │
│                             ▼                                │
│                    ┌────────────────┐                        │
│                    │  SkillRegistry │  ── reload() ──► SSE   │
│                    └────────┬───────┘                        │
│                             ▼                                │
│                    ┌────────────────┐                        │
│                    │     Router     │  ── every dispatch ──► │
│                    │  (by group)    │      usage_log + bus   │
│                    └────────┬───────┘                        │
│                             ▼                                │
│                    ┌────────────────┐                        │
│                    │ RoundRobinPool │  ── cooldown events ──►│
│                    │  (filtered)    │                        │
│                    └────────┬───────┘                        │
│                             ▼                                │
│                    ┌────────────────┐                        │
│                    │  AccountRepo   │  ── tags CRUD          │
│                    │  (SQLite WAL)  │                        │
│                    └────────────────┘                        │
└──────────────────────────────────────────────────────────────┘
           │                                  ▲
           │ HTTP + SSE                       │ reqwest + eventsource-client
           ▼                                  │
┌──────────────────────────────────────────────────────────────┐
│               routeforge-tui (Rust + ratatui)               │
│  Tabs: [Accounts] [Skills] [Usage] [Logs]                   │
│  Live updates from SSE, actions via POST                     │
└──────────────────────────────────────────────────────────────┘
```

## Plugin discovery

### Manifest format

A plugin is a local TOML file in `~/.routeforge/plugins/`:

```toml
# ~/.routeforge/plugins/web-scrape.toml
module = "my_skills.scraper"
attr = "WebScrapeSkill"
info = { name = "web-scrape", description = "...", requires_account = true, provider_group = "scrape" }
```

The module path is resolved relative to `sys.path`. The gateway does not run `pip install`. Users either install the package themselves or place the module on `PYTHONPATH`.

### Loading

`PluginDiscovery.scan(plugins_dir)` walks `*.toml` files, validates the
manifest, then `importlib.import_module(module)` + `getattr(module, attr)`
yields the class. The class is registered via the existing `SkillRegistry.register()` path.

The manifest is authoritative: `info.description`, `info.provider`,
`info.provider_group`, and `info.requires_account` override the class
attributes, so editing a TOML is enough to change behavior.

A malformed manifest is reported on stderr and skipped — one bad file never
blocks startup. `PluginDiscovery.scan_strict` raises instead, for the CLI.

### Persistence

Loaded plugins are written to the `plugins` table, including the `attr` column,
so a restart re-imports exactly the class the manifest named instead of
guessing. On startup, `SkillRegistry.load_persisted()` re-imports enabled rows
whose manifest is still on disk; a row whose manifest has disappeared is
disabled with the reason stored on it. `load_external()` skips any name whose
row is already disabled, so a failed plugin is never retried behind the
operator's back. `routeforge skills list` surfaces those as
`missing_source: true`.

### Reload

`SkillRegistry.reload()` does the following atomically:

1. Snapshot current registry.
2. Clear and re-scan all sources.
3. Diff new vs old.
4. Emit `skills/reloaded` event with the diff.
5. Trigger `notifications/tools/list_changed` on every connected MCP session.

Manual only. No watchdog.

## Provider groups and tags

### Model

- `Account.tags: list[str]` (default `[]`).
- `Skill.provider_group: str | None` (default `None`).

### Dispatch

```python
def _candidates(self, skill: Skill) -> list[Account]:
    group = skill.info.provider_group
    if group:
        return self._repo.list_by_tag(group)
    return self._repo.list_by_provider(skill.provider)


async def _resolve(self, skill, account_label):
    if account_label is not None:
        return self._pin_account(skill, account_label), False

    candidates = self._candidates(skill)
    if not candidates:
        if not skill.requires_account:
            return _EphemeralAccount(provider=skill.provider), True
        raise NoAccountsForGroup(...) if skill.info.provider_group else AllAccountsCooling(...)

    account = await self._pool.pick(candidates)
    if account is None:
        ...
    return account, False
```

### Coexistence with the 1-to-1 model

If `provider_group` is `None`, dispatch falls back to the existing behavior. If
no account carries the group tag, dispatch raises `NoAccountsForGroup`, which
the HTTP layer renders as HTTP 400 with `{"error": "no_accounts_for_group"}`.

### MCP `listChanged` with the current SDK

`FastMCP` builds its `InitializationOptions` with a default
`NotificationOptions` and its constructor does not accept an override, so
`capabilities.tools.listChanged` would be advertised as false. `build_server`
patches `create_initialization_options` on the low-level server instance to pass
`NotificationOptions(tools_changed=True)`. Drop that patch once the SDK exposes
the option on `FastMCP`.

### Where the list-changed notification is sent from

`send_tool_list_changed()` lives on `ServerSession`, not on the low-level
`Server`. The low-level server exposes the active session only through the
`request_ctx` ContextVar, which is populated *while a request is being
handled* and raises `LookupError` outside it.

So the notification is sent from inside the `reload_skills` tool, not from a
background bridge task draining the bus:

```python
@server.tool()
async def reload_skills() -> dict[str, Any]:
    diff = runtime.registry.reload()
    await notify_list_changed(runtime)   # uses inner.request_context.session
    return diff
```

`notify_list_changed` returns `False` when no session is in scope, which is the
correct behavior for every path that is not an MCP tool call. Reloads triggered
over HTTP (`POST /v1/skills/manage/reload`) are a different process in the
current deployment, so they cannot reach an MCP session; they publish
`skill.reloaded` and `mcp.tools.list_changed` on the event bus instead, which is
how SSE clients (the TUI, `routeforge events`) observe them.

## Event bus and SSE

### In-process bus

`EventBus` is an `asyncio` pub/sub. Subscribers get an `asyncio.Queue` per subscription. The bus is fire-and-forget; subscribers that fall behind drop events (logged).

Event types:

| Event | Payload | Emitted by |
|---|---|---|
| `account.cooldown_started` | `{account_id, until, reason}` | `RoundRobinPool.mark_failure` |
| `account.recovered` | `{account_id}` | `RoundRobinPool.mark_success` (when out of cooldown) |
| `account.disabled` | `{account_id}` | TUI action or CLI |
| `skill.reloaded` | `{added: [...], removed: [...], updated: [...]}` | `SkillRegistry.reload` |
| `usage.tick` | `{window: "1m", requests: N, errors: M}` | Event loop (every 60s) |
| `call.completed` | `{skill, account_id, status, latency_ms}` | `Router.dispatch` |

### SSE endpoint

`GET /v1/events` (no auth, loopback-only by default like the rest). Stream is text/event-stream, each event is a JSON object on one line under the `data:` field. Client reconnects automatically on disconnect; latest event is replayed from a 100-event ring buffer (last 5 minutes).

Heartbeat every 15s to keep proxies happy.

## SQLite schema additions

```sql
-- Loaded plugins
CREATE TABLE IF NOT EXISTS plugins (
    name          TEXT PRIMARY KEY,
    source        TEXT NOT NULL CHECK(source IN ('builtin', 'plugin', 'manifest')),
    module_path   TEXT,
    attr          TEXT,                     -- class name from the manifest
    manifest_path TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    loaded_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error         TEXT                      -- why the plugin is disabled
);

-- usage_log gains columns. `skill` → `skill_name` and `status_code` → `status`
-- are renames performed by ALTER TABLE ADD COLUMN plus a backfill, so rows
-- written by bootstrap-core survive.
ALTER TABLE usage_log ADD COLUMN skill_name     TEXT;
ALTER TABLE usage_log ADD COLUMN status         TEXT;
ALTER TABLE usage_log ADD COLUMN provider_group TEXT;
ALTER TABLE usage_log ADD COLUMN tags           TEXT;   -- JSON array

-- Daily aggregates (rolled up by a periodic task)
CREATE TABLE IF NOT EXISTS usage_daily (
    day             TEXT NOT NULL,         -- YYYY-MM-DD
    skill_name      TEXT NOT NULL,
    account_id      INTEGER NOT NULL,
    status          TEXT NOT NULL,
    request_count   INTEGER NOT NULL,
    error_count     INTEGER NOT NULL,
    avg_latency_ms  REAL NOT NULL,
    p95_latency_ms  REAL NOT NULL,
    PRIMARY KEY (day, skill_name, account_id, status)
);

CREATE INDEX IF NOT EXISTS idx_usage_log_skill_time
    ON usage_log(skill_name, ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_log_account_time
    ON usage_log(account_id, ts DESC);

-- Account tags and the operator-controlled enabled flag
ALTER TABLE accounts ADD COLUMN tags    TEXT NOT NULL DEFAULT '[]';
ALTER TABLE accounts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
```

Migration runs on `db.migrate()`, called from `db.connect()`. Every step is
guarded by an existence check, so it is a no-op on a current database.

## Pool selection

`RoundRobinPool.pick(candidates)` receives the candidate set the router already
filtered. The pool never sees tags — that is a routing concern. `acquire(provider)`
remains as a thin wrapper for callers that have not moved to explicit sets.

The pool keys state by `account.provider`, so a provider-group pool is keyed by
the provider of the first candidate and re-synced on every `pick`. Cooldowns,
the cursor, and per-account locks survive that re-sync.

`snapshot()` has two shapes:

- `snapshot()` → `{accounts: {<id>: {state, cooldown_until,
  cooldown_remaining_seconds, consecutive_failures, last_used_at, last_error,
  tags, label, provider}}}` — what the TUI Accounts tab consumes.
- `snapshot(provider)` → the legacy `{provider, accounts, cooldowns, state}`
  shape.

## Error codes

Dispatch failures carry a machine-readable `error_code` alongside the
human-readable message, so HTTP status mapping no longer depends on string
matching:

| `error_code` | HTTP | Body |
|---|---|---|
| `no_accounts_for_group` | 400 | `{"error": "no_accounts_for_group", "detail": ...}` |
| `account_not_found` | 400 | `{"error": "account_not_found", "detail": ...}` |
| `all_accounts_cooling` | 503 | `{"error": "all_accounts_cooling", ...}` + `Retry-After: 60` |
| (skill errors) | 502 | `{"error": "<message>"}` |

`all_accounts_cooling` keeps the legacy message text
`all accounts for provider '<p>' are cooling down` so existing string matching
keeps working.


## TUI (Rust + ratatui)

### Static-review findings

The TUI could not be compiled on the machine that wrote it: `rustc.exe`,
`cargo-fmt.exe`, and `clippy-driver.exe` are blocked by a machine-level App
Control policy (`os error 4551`). A static review against the ratatui 0.29 /
reqwest 0.12 / eventsource-stream 0.2 APIs found and fixed:

- `Connection` derived `Copy` while carrying `Disconnected(String)`.
- `PoolAccount` derived `Eq` while carrying an `f64`.
- `Row::new(vec![...])` mixed `Span` and `Line`; ratatui unifies cells through
  `Cell::from`, and a bare `vec!` forces every element to one type.
- `r`, `space`, and `d` returned actions that `main.rs` discarded, so the three
  mutating keys did nothing. They now issue the documented `POST` calls against
  the selected (filter-aware) account and report the outcome in the footer.
- `ui::help::draw` was never called, which `cargo clippy -D warnings` treats as
  dead code. It is now an overlay on `?`.
- `poll_key` was `async` but called the blocking `crossterm::event::poll` for a
  full tick on a tokio worker, delaying SSE events; it now uses
  `spawn_blocking`.
- `api::events::run` returned `()`, so reconnects always resumed from event 0
  and replayed the whole ring buffer. It now returns the last id forwarded and
  `spawn_event_loop` resumes from it.

### Crate

```toml
# crates/routeforge-tui/Cargo.toml
[package]
name = "routeforge-tui"
version = "0.1.0"
edition = "2021"

[dependencies]
ratatui = "0.29"
crossterm = "0.28"
reqwest = { version = "0.12", features = ["json", "stream"] }
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
eventsource-stream = "0.2"
anyhow = "1"
chrono = { version = "0.4", features = ["serde"] }
humantime = "2"
```

### Layout

```
┌─ routeforge ─────────────────────────────────────────────────────────┐
│ [1] Accounts  [2] Skills  [3] Usage  [4] Logs  · 12 accounts  5 skill │
├──────────────────────────────────────┬───────────────────────────────┤
│ ACCOUNTS (3 cooldown)                │ SKILLS                        │
│ ▣ fc1   firecrawl  active   [scrape] │ ▣ firecrawl/scrape  builtin   │
│ ▣ fc2   firecrawl  active   [scrape] │   ↳ 3 accounts, group=scrape  │
│ ▣ tv1   tavily     active   [scrape] │ ▣ echo             builtin    │
│ ▣ exa1  exa        cooldown [scrape] │ ▣ tavily/search    plugin     │
│ ▣ oai1  openai     active            │   ↳ 1 account, group=search   │
│ ▣ ant1  anthropic  active            │ ▣ exa/search       plugin     │
│                                      │                               │
│ [a] Add  [space] Toggle  [d] Disable │ [↩] Call  [r] Reload  [i] Info │
└──────────────────────────────────────┴───────────────────────────────┘
 footer: 124 calls today · 3 in cooldown · /search · q quit
```

### Live updates

The TUI keeps one SSE connection open. Each event updates an in-memory `AppState` struct. The main loop ticks at 4Hz to repaint (cheap, ratatui is fast). The loop never blocks on the network — SSE updates are dispatched onto a `tokio::sync::mpsc` consumed by the UI thread.

### Actions

| Key | Action | HTTP call |
|---|---|---|
| `r` | Reload skills | `POST /v1/skills/manage/reload` |
| `space` | Toggle enabled | `POST /v1/accounts/manage/toggle` |
| `a` | Add account | opens form (text input within TUI) |
| `d` | Disable account | `POST /v1/accounts/manage/disable` |
| `/` | Search/filter | local filter, no network |
| `1`..`4` | Switch tab | local |
| `q` | Quit | local |

### Communication contract

The TUI never writes to SQLite directly. All writes go through the core's HTTP API. The TUI is a thin client.

## CLI (Python + Typer)

```bash
routeforge skills list [--source builtin|plugin|all]
routeforge skills add --name X --from-toml <path>
routeforge skills remove <name>
routeforge skills reload

routeforge accounts tag <label> --add scrape,web
routeforge accounts untag <label> --remove scrape
routeforge accounts list [--tag scrape]

routeforge plugins install <github-url>     # clones to ~/.routeforge/plugins/
routeforge plugins list

routeforge events                            # tail SSE for debugging

routeforge tui                               # alias for invoking the Rust binary
```

## MCP server changes

- Capability declaration gains `listChanged: true`.
- On `SkillRegistry.reload()`, every connected session receives `notifications/tools/list_changed`.
- New tools:
  - `reload_skills()` — manually trigger reload from MCP context
  - `list_plugins()` — list loaded plugins with their source path
  - `tag_account(label, add, remove)` — manage account tags
- New optional transport: streamable-HTTP at `/mcp`. Activated by `ROUTE_FORGE_MCP_HTTP_PORT`. Bearer token auth optional via `ROUTE_FORGE_MCP_HTTP_TOKEN`.

## Error semantics

- Plugin manifest invalid → 1 log line, skip plugin, do not crash.
- Module import failure → 1 log line, mark plugin as `enabled=0`, write reason to `plugins.error` column.
- Account with `tags=[]` and skill with `provider_group` set → `RouterError("no_accounts_for_group")`, HTTP 400, MCP `isError: true`.
- SSE client falls behind → drop with a counter in metrics; core keeps running.
- Plugin removal from disk → does not unload automatically; `routeforge skills list` shows it with `missing_source: true`.
