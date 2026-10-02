# cli

## Purpose

The CLI is the primary operator surface for terminal-first workflows. It exposes commands for managing skills, plugins, accounts, and live event observation without needing the HTTP API or the TUI.

## ADDED Requirements

### Requirement: Skill commands

The CLI MUST expose `routeforge skills {list,add,remove,reload}`.

#### Scenario: List shows source column

- **WHEN** the user runs `routeforge skills list`
- **THEN** the output MUST be a table with columns: `name`, `source` (`builtin`|`plugin`|`manifest`), `requires_account`, `provider_group`

#### Scenario: List with source filter

- **WHEN** the user runs `routeforge skills list --source plugin`
- **THEN** only skills with `source=plugin` are shown

#### Scenario: Add from manifest

- **WHEN** the user runs `routeforge skills add --from-toml ~/.routeforge/plugins/web-scrape.toml`
- **THEN** the manifest is parsed, the skill is loaded, persisted in the `plugins` table, and listed by `routeforge skills list`

#### Scenario: Remove unregisters and deletes row

- **WHEN** the user runs `routeforge skills remove web-scrape`
- **THEN** the skill is unregistered from the live registry, the row is deleted from `plugins`, and a `skill.reloaded` event is emitted

#### Scenario: Reload rescans all sources

- **WHEN** the user runs `routeforge skills reload`
- **THEN** the registry clears, re-scans `~/.routeforge/plugins/` and the manifest dir, diffs the result, and emits `skill.reloaded` with the diff payload

### Requirement: Account tag commands

The CLI MUST expose `routeforge accounts tag <label>` and `routeforge accounts untag <label>`.

#### Scenario: Tag a single account

- **WHEN** the user runs `routeforge accounts tag fc1 --add scrape,web`
- **THEN** the account's `tags` field becomes `["scrape", "web"]` and the change is persisted

#### Scenario: Untag removes specified tags only

- **WHEN** the user runs `routeforge accounts untag fc1 --remove scrape`
- **AND** `fc1` had `tags=["scrape", "web"]`
- **THEN** `fc1` ends up with `tags=["web"]`

### Requirement: Events tail command

The CLI MUST expose `routeforge events` which tails the SSE stream for debugging.

#### Scenario: Events tail

- **WHEN** the user runs `routeforge events`
- **THEN** the CLI connects to `GET /v1/events` and prints one line per event as JSON, until the user presses `Ctrl+C`

### Requirement: TUI launch

The CLI MUST expose `routeforge tui` which launches the bundled Rust binary.

#### Scenario: TUI launches

- **WHEN** the user runs `routeforge tui`
- **THEN** the CLI locates the `routeforge-tui` binary (`PATH` first, then alongside the Python package) and execs it

#### Scenario: Binary not found

- **WHEN** the user runs `routeforge tui` and the binary is not present
- **THEN** the CLI prints instructions to build it with `cargo build --release` and exits with a non-zero code

### Requirement: Standard flags

All commands MUST support `--help` and JSON output (`--json`) where applicable.

#### Scenario: JSON output

- **WHEN** the user runs `routeforge skills list --json`
- **THEN** the output is a JSON array of skill objects
