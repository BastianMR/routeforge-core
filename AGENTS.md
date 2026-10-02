# AGENTS.md — Operating rules for routeforge-core

This repository is governed by the **OpenSpec** spec-driven workflow. Every
change originates as an OpenSpec change under `openspec/changes/<name>/`,
is applied via `/opsx-apply`, and is folded back into `openspec/specs/`
via `/opsx-archive`.

## Source of truth

- **Process rules**: this file. The `bootstrap-core` change proposed a
  `process` capability but never landed one, so there is no
  `openspec/specs/process/spec.md` — do not cite one.
- **Routing schema**: `openspec/specs/routing/spec.md`.
- **Rotation rules**: `openspec/specs/rotation/spec.md`.
- **Secrets**: `openspec/specs/secrets/spec.md`.
- **Skills registry**: `openspec/specs/skills-registry/spec.md`.
- **MCP server**: `openspec/specs/mcp-server/spec.md`.
- **Plugin discovery**: `openspec/specs/skills-discovery/spec.md`.
- **Usage tracking**: `openspec/specs/usage-tracking/spec.md`.
- **Event bus**: `openspec/specs/events/spec.md`.
- **CLI**: `openspec/specs/cli/spec.md`.
- **TUI**: `openspec/specs/tui/spec.md`.
- **OpenSpec workflow (this machine)**: `~/.agents/OPENSPEC.md`.

Always confirm a spec path exists before citing it:
`ls openspec/specs/` lists the live capabilities.

## Repository layout

```
src/routeforge/          Python core: db, accounts, rotation, router, usage,
                         events, plugins, skills, app, mcp_server, runtime
src/routeforge/cli/      Typer commands, one module per noun
crates/routeforge-tui/   Rust + ratatui operator UI (HTTP + SSE client only)
openspec/                spec-driven workflow artifacts
```

`src/routeforge/runtime.py` assembles the object graph. `serve`, `mcp`, and
every CLI command go through `build_runtime()` so they see one registry, one
pool, and one event bus.

The TUI MUST NOT touch SQLite. All reads come from the HTTP API and all writes
are `POST` calls.

## Validation commands

| Area | Commands |
|------|----------|
| Python | `ruff check src tests`, `pytest -q` |
| Rust | `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (from `crates/routeforge-tui`) |
| Specs | `openspec validate --all --strict`, `openspec validate --archived --strict` |

Rust unit tests must cover pure logic only; never render a terminal in a test.

## Change workflow

1. **Explore** — `/opsx-explore "<question>"`.
2. **Propose** — `/opsx-propose "<change-name>"` creates
   `openspec/changes/<name>/` with `proposal.md`, `design.md`, `tasks.md`,
   and one or more `specs/<capability>/spec.md` deltas.
3. **Apply** — `/opsx-apply` walks `tasks.md`. Run `pytest -q` and
   `ruff check src tests` after touching any Python file.
4. **Validate** — `openspec validate --all --strict` plus local tests.
5. **PR** — CI runs `ruff`, `pytest`, `openspec validate --all --strict`,
   and `openspec validate --archived --strict`. CI never hardcodes a change
   name; it discovers active changes.
6. **Archive** — `/opsx-archive <name>` moves the change to
   `openspec/changes/archive/YYYY-MM-DD-<name>/` and merges delta specs
   into `openspec/specs/<capability>/spec.md`. Tick the archive tasks before
   committing, otherwise `--archived` fails in CI.

## Local validation

```bash
ruff check src tests
pytest -q
openspec validate --all --strict
openspec validate --archived --strict
```

## Coding conventions

- Python 3.12, type hints everywhere.
- Async-first (httpx, asyncio).
- No secrets in logs or error messages. The `Secrets` wrapper enforces this.
- Skills subclass `Skill`; add new skills under `src/routeforge/skills/builtin/`
  or ship them as plugins in `~/.routeforge/plugins/`.
- Public API changes go through a capability delta under
  `openspec/changes/<name>/specs/`; no direct edits to `openspec/specs/`
  from `main`.

## Out of scope (v1)

- Token-bucket credit tracking per account.
- OAuth flows for upstream APIs.
- Multi-tenant virtual keys.
- Web admin UI.
- Streaming responses.