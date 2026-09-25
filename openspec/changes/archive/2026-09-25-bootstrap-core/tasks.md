## 1. Bootstrap OpenSpec + project structure

- [x] 1.1 Run `openspec init --tools opencode` from the repo root.
- [x] 1.2 Verify `.opencode/commands/opsx-*.md` and `.opencode/skills/openspec-*/SKILL.md` exist.
- [x] 1.3 Run `openspec new change bootstrap-core` to create the change scaffold.
- [x] 1.4 Write `openspec/config.yaml` with project context, rules, operations.
- [x] 1.5 Write `openspec/changes/bootstrap-core/proposal.md`.
- [x] 1.6 Write `openspec/changes/bootstrap-core/design.md`.
- [x] 1.7 Write `openspec/changes/bootstrap-core/tasks.md` (this file).

## 2. Write the delta specs

- [x] 2.1 Write `openspec/changes/bootstrap-core/specs/routing/spec.md` - request/response shapes for OpenAI-compatible + skill-typed endpoints.
- [x] 2.2 Write `openspec/changes/bootstrap-core/specs/rotation/spec.md` - round-robin + cooldown rules.
- [x] 2.3 Write `openspec/changes/bootstrap-core/specs/secrets/spec.md` - Fernet encryption + master key.
- [x] 2.4 Write `openspec/changes/bootstrap-core/specs/skills-registry/spec.md` - skill discovery + execution.
- [x] 2.5 Write `openspec/changes/bootstrap-core/specs/mcp-server/spec.md` - MCP tools exposed.

## 3. Project metadata

- [x] 3.1 Create `pyproject.toml` with Python 3.12, runtime + dev deps, ruff + pytest config.
- [x] 3.2 Rewrite `README.md` describing the gateway, install, usage, MCP integration.
- [x] 3.3 Rewrite `AGENTS.md` pointing at OpenSpec workflow + the new process spec.
- [x] 3.4 Update `CHANGELOG.md` with the bootstrap-core entry.

## 4. Implement core modules

- [x] 4.1 Create `src/routeforge/__init__.py`.
- [x] 4.2 Create `src/routeforge/config.py` - Settings via Pydantic + env vars.
- [x] 4.3 Create `src/routeforge/secrets.py` - Fernet wrapper with master-key validation.
- [x] 4.4 Create `src/routeforge/db.py` - SQLite connection + schema bootstrap.
- [x] 4.5 Create `src/routeforge/models.py` - Pydantic models for Account, SkillSchema, Request, Response.
- [x] 4.6 Create `src/routeforge/accounts.py` - AccountRepo CRUD.
- [x] 4.7 Create `src/routeforge/rotation.py` - RoundRobinPool + CooldownTracker (async-safe).
- [x] 4.8 Create `src/routeforge/router.py` - core dispatch wiring rotation + skills + usage log.

## 5. Skills

- [x] 5.1 Create `src/routeforge/skills/__init__.py`.
- [x] 5.2 Create `src/routeforge/skills/base.py` - Skill ABC + SkillSchemaModel dataclass.
- [x] 5.3 Create `src/routeforge/skills/registry.py` - SkillRegistry with discovery from builtin package.
- [x] 5.4 Create `src/routeforge/skills/builtin/__init__.py` + `echo.py` + `firecrawl.py`.
- [x] 5.5 Create `src/routeforge/skills/builtin/firecrawl.py` - firecrawl/scrape skill.

## 6. HTTP + MCP entry points

- [x] 6.1 Create `src/routeforge/app.py` - FastAPI factory with all v1 endpoints.
- [x] 6.2 Create `src/routeforge/mcp_server.py` - stdio MCP server with list_skills / call_skill / list_accounts / get_usage.
- [x] 6.3 Create `src/routeforge/cli/__init__.py` + `main.py` - Typer CLI.

## 7. Tests

- [x] 7.1 Create `tests/conftest.py` with fixtures for tmp DB + secrets.
- [x] 7.2 Create `tests/test_secrets.py` - round-trip + missing-key failure.
- [x] 7.3 Create `tests/test_rotation.py` - cursor advances; cooldown excludes; pool exhausted returns None.
- [x] 7.4 Create `tests/test_router.py` - skill dispatch + cooldown on simulated 429.
- [x] 7.5 Create `tests/test_skills.py` - echo returns args; firecrawl builds correct request via mocked httpx.

## 8. CI

- [x] 8.1 Replace `.github/workflows/ci.yml` with python job: setup-python@v5, pip install -e ., ruff check, pytest, openspec validate bootstrap-core.
- [x] 8.2 CI YAML parses cleanly.

## 9. Verify

- [x] 9.1 `ruff check src tests` exits 0.
- [x] 9.2 `pytest -q` exits 0 (19 tests pass).
- [x] 9.3 `openspec validate bootstrap-core` exits 0.
- [x] 9.4 `openspec status --change bootstrap-core` shows every artifact `[x]`.

## 10. Archive

- [ ] 10.1 `openspec archive bootstrap-core --yes` moves the change to `openspec/changes/archive/2026-09-25-bootstrap-core/`.
- [ ] 10.2 `openspec validate --all` exits 0.