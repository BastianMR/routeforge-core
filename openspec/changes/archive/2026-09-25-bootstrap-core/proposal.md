# Proposal

## Why

The user wants a personal gateway that fronts N upstream AI/tool APIs (Firecrawl, Tavily, etc.) and rotates between multiple accounts of each provider to multiply free quotas and stay under per-key rate limits. Existing solutions (LiteLLM, OmniRoute) optimize for LLM providers and don't model non-LLM skills well. We need a small, OpenSpec-driven Python project that establishes the core motor: a FastAPI HTTP layer, an encrypted SQLite account store, round-robin rotation with cooldown, a pluggable skills registry, and an MCP server so any AI agent (Claude Code, Cursor, opencode, etc.) can consume the gateway without per-tool configuration.

## What Changes

- Initialize OpenSpec via `openspec init --tools opencode` (already run during this change).
- Create the Python package `routeforge` under `src/routeforge/` with: config loader, SQLite-backed accounts repository, Fernet-encrypted secrets, round-robin rotation pool with cooldown tracker, router core, skill base class + registry, two builtin skills (`echo`, `firecrawl/scrape`), FastAPI HTTP app, Typer CLI, and a stdio MCP server exposing `list_skills`, `call_skill`, `list_accounts`, `get_usage`.
- Add `pyproject.toml` (uv-managed) declaring Python 3.12, runtime deps (fastapi, uvicorn, httpx, typer, pydantic, cryptography, mcp) and dev deps (pytest, pytest-asyncio, ruff).
- Add a pytest suite covering rotation, secrets, router, and skills.
- Add GitHub Actions CI: ruff lint + pytest on Python 3.12 + `openspec validate bootstrap-core`.
- Update `README.md`, `AGENTS.md`, `CHANGELOG.md` to describe the project.

## Capabilities

### New Capabilities

- `routing`: shape of incoming requests (OpenAI-compatible + skill-typed) and shape of responses.
- `rotation`: round-robin account selection with cooldown rules on 429/402/5xx.
- `secrets`: Fernet encryption of API keys at rest with master-key env var.
- `skills-registry`: how skills are discovered and invoked.
- `mcp-server`: tools exposed via Model Context Protocol (stdio).

### Modified Capabilities

None. All five capabilities are introduced fresh.

## Impact

- Files added (~25):
  - `pyproject.toml`, `src/routeforge/*.py`, `tests/test_*.py`, `.github/workflows/ci.yml`, `openspec/changes/bootstrap-core/{proposal,design,tasks}.md`, `openspec/changes/bootstrap-core/specs/<cap>/spec.md`, `openspec/config.yaml`, `examples/config.yaml`.
- Files rewritten:
  - `README.md`, `AGENTS.md`, `CHANGELOG.md`, `.github/workflows/ci.yml`.
- Files unchanged: `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `.editorconfig`, `.gitignore`, `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `docs/`, `scripts/`.
- Runtime impact: the gateway can be run locally via `routeforge serve` (HTTP) or `routeforge mcp` (stdio). The HTTP server defaults to `127.0.0.1:8080`. The stdio MCP server speaks JSON-RPC over stdin/stdout.
- CI impact: `validate-config` job is replaced by `python` job that runs `ruff`, `pytest`, and `openspec validate bootstrap-core`.
- Downstream consumers: any MCP-compatible agent that can read a stdio MCP server (Claude Code, Cursor, opencode, etc.) consumes it without per-skill configuration.