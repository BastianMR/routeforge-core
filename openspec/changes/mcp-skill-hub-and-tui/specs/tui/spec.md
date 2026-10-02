# tui

## Purpose

The TUI is a Rust binary in the same workspace as the Python core. It provides a live operator view of accounts, skills, usage, and event logs by consuming the core's HTTP API and SSE stream. It does not write to SQLite directly — all mutations go through HTTP.

## ADDED Requirements

### Requirement: Workspace layout

The repository MUST contain a Cargo workspace at the root.

#### Scenario: Workspace structure

- **WHEN** the repository is cloned
- **THEN** `Cargo.toml` at the root declares members `["crates/*"]`
- **AND** `crates/routeforge-tui/` contains the TUI crate

### Requirement: Build produces a binary

`cargo build --release` in `crates/routeforge-tui/` MUST produce `target/release/routeforge-tui` (or `.exe` on Windows).

#### Scenario: Release build succeeds

- **WHEN** the user runs `cargo build --release --manifest-path crates/routeforge-tui/Cargo.toml`
- **THEN** the build completes with no errors and the binary exists at the expected path

### Requirement: Connection to core

The TUI MUST connect to the core via HTTP at the URL from `ROUTE_FORGE_URL` (default `http://127.0.0.1:8787`).

#### Scenario: Custom URL

- **WHEN** `ROUTE_FORGE_URL=http://192.168.1.10:8787 routeforge-tui`
- **THEN** the TUI connects to that address

#### Scenario: Core unreachable

- **WHEN** the core at the configured URL is not running
- **THEN** the TUI displays a connection error banner and retries every 5 seconds

### Requirement: Tabs

The TUI MUST expose four tabs, switchable with keys `1`..`4`.

#### Scenario: Accounts tab

- **WHEN** the user presses `1`
- **THEN** the Accounts panel shows a table with columns: `label`, `provider`, `tags`, `status` (active/cooldown/disabled), `last_used`

#### Scenario: Skills tab

- **WHEN** the user presses `2`
- **THEN** the Skills panel shows a table with columns: `name`, `source`, `provider_group`, `requires_account`, `account_count`

#### Scenario: Usage tab

- **WHEN** the user presses `3`
- **THEN** the Usage panel shows live sparkline charts (requests/min and errors/min) and a top-skills list

#### Scenario: Logs tab

- **WHEN** the user presses `4`
- **THEN** the Logs panel shows the last 200 events from SSE in reverse chronological order

### Requirement: Live updates via SSE

The TUI MUST subscribe to `GET /v1/events` and update its in-memory state on every received event.

#### Scenario: Cooldown event updates account row

- **WHEN** the core emits `account.cooldown_started` for account id 5
- **THEN** the TUI updates the row for account 5 to show `status=cooldown` without waiting for a manual refresh

#### Scenario: Skill reload updates skills panel

- **WHEN** the core emits `skill.reloaded`
- **THEN** the TUI re-fetches `GET /v1/skills` and updates the Skills panel

### Requirement: Actions

The TUI MUST support the following keyboard actions on the focused panel:

| Key | Action | HTTP call |
|---|---|---|
| `r` | Reload skills | `POST /v1/skills/manage/reload` |
| `space` | Toggle account enabled | `POST /v1/accounts/manage/toggle` |
| `a` | Add account (opens form) | `POST /v1/accounts` |
| `d` | Disable account | `POST /v1/accounts/manage/disable` |
| `/` | Local filter | none |
| `q` | Quit | none |

#### Scenario: Reload from TUI

- **WHEN** the user presses `r` on the Skills panel
- **THEN** the TUI sends `POST /v1/skills/manage/reload` and waits for the `skill.reloaded` event

#### Scenario: Toggle account

- **WHEN** the user selects an account and presses `space`
- **THEN** the TUI sends `POST /v1/accounts/manage/toggle` with the account id; on success the row updates to reflect the new state

### Requirement: Visual style

The TUI MUST use color and glyphs to convey state at a glance:

- Green check for active accounts and successful calls
- Yellow dot for accounts in cooldown
- Red X for disabled accounts or error statuses
- Cyan labels for skills, magenta for tags
- A persistent footer shows `requests today`, `in cooldown`, `errors/min`, and the SSE connection status

#### Scenario: Cooldown visible

- **WHEN** an account is in cooldown
- **THEN** its row shows a yellow dot and the remaining cooldown time in seconds

### Requirement: No direct database writes

The TUI MUST NOT open, write, or modify the SQLite database directly.

#### Scenario: TUI runs while core is offline

- **WHEN** the TUI is launched but the core is not running
- **THEN** the TUI does not crash, does not create or modify any file in `~/.routeforge/`, and shows a connection error banner
