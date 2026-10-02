# mcp-skill-hub-and-tui

## Why

`bootstrap-core` shipped a working single-host, multi-account AI API gateway with MCP stdio and OpenAI-compatible HTTP. Two gaps remain that block the original "one point of configuration for every agent" goal:

1. **Skills are static.** Today, every skill must live inside the `routeforge.skills.builtin` Python package. Adding a skill requires editing the source tree, reinstalling, and restarting. Real-world skill lifecycles are not coupled to the gateway release cycle.

2. **Accounts with the same role cannot share load.** The router maps `skill → provider` 1-to-1, so three Firecrawl keys are three isolated pools. Cross-provider equivalents (Firecrawl + Tavily + Exa for "web scrape") cannot be rotated as a group.

3. **Usage and state are invisible.** Operators cannot see which accounts are hot, which skills are failing, or which providers are saturated. There is no live view of the gateway.

This change introduces plugin discovery, account tagging with provider groups, an event bus with SSE exposure, a Rust TUI, and persisted usage tracking, all built on the existing SQLite database.

## What changes

### New capabilities

- **Plugin discovery.** Skills loaded from local `.toml` manifests in `~/.routeforge/plugins/`, each pointing to a Python module+attr. Loaded plugins persisted in a new `plugins` SQLite table so restarts remember them.
- **Usage tracking.** Every dispatch writes a row to `usage_log` with skill name, account id, status, latency, and timestamp. Aggregations exposed via HTTP and streamed via SSE.
- **TUI.** Rust workspace member `routeforge-tui` consuming the core over HTTP + SSE. ratatui-based, 4 tabs (Accounts, Skills, Usage, Logs).
- **Event bus.** In-process pub/sub with SSE endpoint `GET /v1/events` so external clients (TUI, future web UI, observability) get live updates without polling.
- **CLI.** New `skills` and `accounts tag/untag` subcommands for terminal-first operations.

### Modified capabilities

- **Skills registry.** Now loads from three sources (builtin + plugin + manifest YAML), exposes `reload()`, and reads the `plugins` table on startup.
- **Rotation.** `Account.tags` (list of strings, default `[]`). Pool filter happens before the round-robin picks.
- **Routing.** `Skill.provider_group` (optional string). Dispatch filters the candidate account set by tag intersection.
- **MCP server.** Declares `listChanged: true`, emits `notifications/tools/list_changed` on reload, gains optional streamable-HTTP transport.

## Out of scope

- Web UI (TUI is the primary operator surface for v1).
- Centralized plugin marketplace. Plugins install from local `.toml` or `routeforge plugins install <github-url>` clones the repo locally.
- Hot-reload / filesystem watchdog. Reload is manual (`routeforge skills reload` or `r` in the TUI).
- Multi-tenant auth. Single-user, loopback-only, same as `bootstrap-core`.
- Cross-host replication. SQLite is local-only.

## Compatibility

- `bootstrap-core` stays intact. `Account.tags` defaults to `[]` and `Skill.provider_group` defaults to `None`, preserving the existing 1-to-1 dispatch.
- HTTP API surface is additive. Every existing endpoint keeps its current shape.
- The MCP server's existing 4 tools keep their current shapes; new tools are added.
- SQLite schema gets two new tables (`plugins`, expanded `usage_log` columns). A migration runs on startup; old rows are preserved.
