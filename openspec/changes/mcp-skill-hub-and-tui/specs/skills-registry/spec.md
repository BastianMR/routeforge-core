# Skills Registry Specification

## Purpose

Define the contract for pluggable skills: discovery at startup, schema declaration, execution signature, and error semantics. A skill is a small class subclassing `Skill`; the registry loads them automatically.

## MODIFIED Requirements

### Requirement: Skill Base Class

The system SHALL define a `Skill` abstract base class with attributes `name: str`, `provider: str`, `description: str`, and method `async def execute(account, args, http) -> dict`.

#### Scenario: Subclassing

- **WHEN** a developer writes a class inheriting `Skill` and sets `name`, `provider`, `description`
- **THEN** the registry can load it without further registration code

### Requirement: Skill Schema Is Declared

The system SHALL require every skill to expose a `schema()` method returning a `SkillSchema` with `inputs` and `outputs` as JSON-Schema-shaped dicts.

#### Scenario: Listing a skill

- **WHEN** the registry returns a skill
- **THEN** the response includes `schema.inputs` and `schema.outputs` so clients can validate arguments before calling

### Requirement: Built-in Skills Discovered Automatically

The system SHALL discover every skill under `routeforge.skills.builtin` at startup, in addition to any plugin-manifested skills under `~/.routeforge/plugins/`. The registry MUST persist each loaded plugin in the `plugins` SQLite table so restarts remember it.

#### Scenario: Boot discovery

- **WHEN** the daemon starts
- **THEN** every class subclassing `Skill` inside `routeforge.skills.builtin` is registered with its declared `name`

#### Scenario: Boot discovery includes plugins

- **WHEN** the daemon starts
- **AND** `~/.routeforge/plugins/` contains one or more `.toml` manifests
- **THEN** every class subclassing `Skill` inside `routeforge.skills.builtin` is registered
- **AND** every successfully loaded plugin from the manifests is registered and a row is written to the `plugins` table with `source='plugin'`

#### Scenario: Plugin manifest missing required field

- **WHEN** a manifest under `~/.routeforge/plugins/` is missing `module`, `attr`, or `info.name`
- **THEN** the registry MUST log a warning identifying the file and the missing field, and MUST NOT register the skill

#### Scenario: Plugin import failure

- **WHEN** a manifest references a module that cannot be imported
- **THEN** the registry MUST mark the plugin `enabled=0` in the `plugins` table, store the error in `plugins.error`, and continue startup without crashing

### Requirement: Skill Receives an Account and an HTTP Client

The system SHALL call `skill.execute(account, args, http)` where `account` exposes at minimum `api_key`, `base_url`, `metadata`, and `tags: list[str]`; `http` is a shared `httpx.AsyncClient`.

#### Scenario: Skill makes upstream call

- **WHEN** the skill calls `http.post(...)` with `headers={"Authorization": f"Bearer {account.api_key}"}`
- **THEN** the upstream receives the correct bearer token

#### Scenario: Skill reads account tags

- **WHEN** a skill needs to inspect which tags the chosen account carries
- **THEN** `account.tags` is available on the `Account` object passed to `execute()`

### Requirement: Skill Errors Surface to Caller

The system SHALL propagate `SkillError` (and its subclasses) to the caller as `{"error": "<message>"}` with HTTP 502. The error MUST be recorded in `usage_log` with the appropriate status (`error_4xx`, `error_5xx`, or `error_network`).

#### Scenario: Skill raises SkillError

- **WHEN** `skill.execute()` raises `SkillError("upstream 503")`
- **THEN** the daemon returns HTTP 502 with `{"error": "upstream 503"}` and the account is NOT marked cooled

#### Scenario: Usage row on error

- **WHEN** `skill.execute()` raises `SkillError("upstream 503")`
- **THEN** a row is written to `usage_log` with `status='error_5xx'` and the error message

### Requirement: Two Built-in Skills Ship in v1

The system SHALL ship `echo` (returns args unchanged) and `firecrawl/scrape` (POSTs to the configured base_url) as built-in skills.

#### Scenario: Echo skill

- **WHEN** a client calls `echo` with `{"args": {"x": 1}}`
- **THEN** the response is `{"result": {"x": 1}}`

#### Scenario: Firecrawl scrape skill

- **WHEN** a client calls `firecrawl/scrape` with `{"args": {"url": "https://example.com", "formats": ["markdown"]}}`
- **THEN** the skill POSTs to `{account.base_url}/v1/scrape` and returns the upstream JSON

## ADDED Requirements

### Requirement: Skill Sources Are Three

The registry MUST support three discovery sources:

1. **Built-in**: classes under `routeforge.skills.builtin` (always loaded).
2. **Plugin**: TOML manifests in `~/.routeforge/plugins/` (loaded on startup and persisted in the `plugins` table).
3. **Manifest**: an optional YAML file pointed to by `ROUTE_FORGE_MANIFEST_PATH` (declarative skills that wrap a remote HTTP endpoint; reserved for future use and listed but not actively loaded in v1).

Each registered skill carries a `source` attribute with value `"builtin"`, `"plugin"`, or `"manifest"`.

#### Scenario: Listing skills includes source

- **WHEN** a client calls `GET /v1/skills` or the MCP `list_skills` tool
- **THEN** each skill in the response includes a `source` field with one of the three values

### Requirement: Reload Rescans Sources

`SkillRegistry.reload()` MUST clear the registry, re-scan every source directory, re-import all enabled plugins from the `plugins` table, and emit a `skill.reloaded` event containing `added`, `removed`, and `updated` skill name lists.

#### Scenario: Reload picks up new plugin

- **WHEN** the user runs `routeforge skills reload` after dropping a new manifest into `~/.routeforge/plugins/`
- **THEN** the new skill appears in `GET /v1/skills` and a `skill.reloaded` event with the new name under `added` is published

#### Scenario: Reload removes deleted manifest

- **WHEN** a manifest that previously loaded a plugin is removed from disk
- **AND** the row still exists in `plugins` with `enabled=1`
- **THEN** the skill stays loaded (manifest removal from disk is not an automatic unload; the user must run `routeforge skills remove <name>` to fully unregister)
- **AND** `routeforge skills list` shows the skill with `missing_source: true`

### Requirement: Source-Aware Listing

The CLI MUST accept `--source builtin|plugin|all` to filter listings by source.

#### Scenario: List plugin skills only

- **WHEN** the user runs `routeforge skills list --source plugin`
- **THEN** only skills with `source='plugin'` are returned
