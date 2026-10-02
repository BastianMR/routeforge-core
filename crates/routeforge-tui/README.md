# routeforge-tui

A read-mostly terminal UI for the [routeforge-core](../../README.md) gateway.

The TUI is a thin client: it never opens the SQLite database. Every read comes
from the core's HTTP API, every mutation is a `POST`, and live updates arrive
over the SSE stream.

```
[routeforge-tui] --HTTP--> GET  /v1/accounts
                  --HTTP--> GET  /v1/skills
                  --HTTP--> GET  /v1/usage?group_by=skill&since=24h
                  --HTTP--> GET  /v1/accounts/pool
                  --HTTP--> POST /v1/skills/manage/reload
                  --HTTP--> POST /v1/accounts/manage/{toggle,disable}
                  --SSE --> GET  /v1/events
```

## Build

Requires a stable Rust toolchain (1.82+) and a running core.

```bash
# from the repository root
cargo build --release --manifest-path crates/routeforge-tui/Cargo.toml
```

The binary lands at `target/release/routeforge-tui` (`.exe` on Windows).

## Run

Either put the binary on `PATH`:

```bash
routeforge-tui
```

or let the Python CLI launch it:

```bash
routeforge serve            # terminal 1
routeforge tui              # terminal 2
```

`routeforge tui` looks for `routeforge-tui` on `PATH` first, then falls back to
`target/release/routeforge-tui` inside the repository, and passes
`ROUTE_FORGE_URL` through to the binary.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `ROUTE_FORGE_URL` | `http://127.0.0.1:8787` | Base URL of the core. |

The default matches the core's default bind address. Point it elsewhere with:

```bash
ROUTE_FORGE_URL=http://192.168.1.10:8787 routeforge-tui
```

When the core is unreachable the TUI shows an offline banner in the footer and
retries every 5 seconds. It does not create or modify anything under
`~/.routeforge/`.

## Layout

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

- Green `OK` — active account
- Yellow `..` — account in cooldown, remaining seconds shown
- Red `XX` — disabled account
- Cyan — skill and account labels
- Magenta — tags

## Keys

| Key | Action | HTTP call |
|-----|--------|-----------|
| `1`..`4` | Switch tab | local |
| `tab` / `backtab` | Cycle tabs | local |
| `/` | Filter (local) | none |
| `?` | Toggle the key overlay | none |
| `up` / `down` | Move selection | local |
| `r` | Reload skills | `POST /v1/skills/manage/reload` |
| `space` | Toggle account enabled | `POST /v1/accounts/manage/toggle` |
| `d` | Disable account | `POST /v1/accounts/manage/disable` |
| `q`, `ctrl+c` | Quit | none |

Account actions apply to the highlighted row, and they honor the active filter:
selection always points into the rows you can actually see. The footer reports
the outcome of each call until the next event replaces it.

## Tests

Unit tests cover pure logic only — no terminal is rendered.

```bash
cargo test --manifest-path crates/routeforge-tui/Cargo.toml
cargo clippy --manifest-path crates/routeforge-tui/Cargo.toml -- -D warnings
cargo fmt --check --manifest-path crates/routeforge-tui/Cargo.toml
```
