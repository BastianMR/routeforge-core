# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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