# AGENTS.md — Operating rules for routeforge-core

This repository is governed by the **OpenSpec** spec-driven workflow. Every
change originates as an OpenSpec change under `openspec/changes/<name>/`,
is applied via `/opsx-apply`, and is folded back into `openspec/specs/`
via `/opsx-archive`.

## Source of truth

- **Process rules**: `openspec/specs/process/spec.md` (post-archive) or
  `openspec/changes/<name>/specs/process/spec.md` (in-flight).
- **Routing schema**: `openspec/specs/routing-schema/spec.md`.
- **Rotation rules**: `openspec/specs/rotation/spec.md`.
- **Secrets**: `openspec/specs/secrets/spec.md`.
- **Skills registry**: `openspec/specs/skills-registry/spec.md`.
- **MCP server**: `openspec/specs/mcp-server/spec.md`.
- **OpenSpec workflow (this machine)**: `~/.agents/OPENSPEC.md`.

## Change workflow

1. **Explore** — `/opsx-explore "<question>"`.
2. **Propose** — `/opsx-propose "<change-name>"` creates
   `openspec/changes/<name>/` with `proposal.md`, `design.md`, `tasks.md`,
   and one or more `specs/<capability>/spec.md` deltas.
3. **Apply** — `/opsx-apply` walks `tasks.md`. Run `pytest -q` and
   `ruff check src tests` after touching any Python file.
4. **Validate** — `openspec validate <name>` plus local tests.
5. **PR** — CI runs `ruff`, `pytest`, and `openspec validate <name>`.
6. **Archive** — `/opsx-archive <name>` moves the change to
   `openspec/changes/archive/YYYY-MM-DD-<name>/` and merges delta specs
   into `openspec/specs/<capability>/spec.md`.

## Local validation

```bash
ruff check src tests
pytest -q
openspec validate <name>
```

## Coding conventions

- Python 3.12, type hints everywhere.
- Async-first (httpx, asyncio).
- No secrets in logs or error messages. The `Secrets` wrapper enforces this.
- Skills subclass `Skill`; add new skills under `src/routeforge/skills/builtin/`.
- Public API changes go through a `process` capability delta; no direct
  edits to `openspec/specs/` from `main`.

## Out of scope (v1)

- Token-bucket credit tracking per account.
- OAuth flows for upstream APIs.
- Multi-tenant virtual keys.
- Web admin UI.
- Streaming responses.
- HTTP/SSE MCP transport (stdio only in v1).