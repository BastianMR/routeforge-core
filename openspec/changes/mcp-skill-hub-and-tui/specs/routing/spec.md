# Routing Specification

## Purpose

Define the request and response shapes of routeforge-cores HTTP endpoints: the skill-typed `POST /skills/{name}/call`, the OpenAI-compatible `POST /v1/chat/completions` with the `skill:` prefix, plus the listing, usage, manage, and SSE event endpoints. This capability is the contract between any HTTP client and the gateway.

## MODIFIED Requirements

### Requirement: Skill-Typed HTTP Endpoint

The system SHALL expose `POST /skills/{name}/call` that accepts a JSON body `{ "args": { ... } }` and returns the skill's output JSON.

#### Scenario: Skill exists

- **WHEN** a client POSTs to `/skills/echo/call` with `{"args": {"x": 1}}`
- **THEN** the daemon returns `{"result": {"x": 1}}` with HTTP 200

#### Scenario: Unknown skill

- **WHEN** a client POSTs to `/skills/does-not-exist/call`
- **THEN** the daemon returns HTTP 404 with `{"error": "skill not found"}`

### Requirement: OpenAI-Compatible Chat Endpoint

The system SHALL expose `POST /v1/chat/completions` that accepts an OpenAI-shaped body and routes to a skill when the `model` field starts with `skill:`.

#### Scenario: Routing to a skill

- **WHEN** a client POSTs `{"model": "skill:echo", "messages": [{"role":"user","content":"hi"}]}`
- **THEN** the daemon extracts `args = {"message": "hi"}` from the last user message and calls `echo`

#### Scenario: Non-skill model

- **WHEN** a client POSTs `{"model": "gpt-4", "messages": [...]}`
- **THEN** the daemon returns HTTP 400 with `{"error": "model must start with 'skill:'"}`

### Requirement: Skills Listing Endpoint

The system SHALL expose `GET /v1/skills` that returns the list of registered skills, each annotated with its `source`.

#### Scenario: Listing registered skills

- **WHEN** a client GETs `/v1/skills`
- **THEN** the daemon returns `[{"name": "echo", "source": "builtin", "description": "...", "schema": {...}, "provider_group": null, "requires_account": false}, ...]`

### Requirement: Accounts Listing Endpoint

The system SHALL expose `GET /v1/accounts` that returns account metadata (never the raw API key), including `tags` and `enabled` fields.

#### Scenario: Listing accounts

- **WHEN** a client GETs `/v1/accounts`
- **THEN** the daemon returns `{"firecrawl": [{"id": 1, "label": "x", "tags": [], "enabled": true, "last_used_at": null}, ...]}` grouped by provider

#### Scenario: Listing accounts with tags

- **WHEN** a client GETs `/v1/accounts` and an account has `tags=["scrape", "web"]`
- **THEN** that account's object includes `"tags": ["scrape", "web"]`

### Requirement: Usage Endpoint

The system SHALL expose `GET /v1/usage?skill=&since=&group_by=` that returns usage stats aggregated by account and skill.

#### Scenario: Filtered usage

- **WHEN** a client GETs `/v1/usage?provider=firecrawl`
- **THEN** the daemon returns `{"firecrawl": {"accounts": [{"id": 1, "calls": 5, "errors": 0}], "skills": [...]}}`

#### Scenario: Filter by skill

- **WHEN** the user calls `GET /v1/usage?skill=firecrawl/scrape&since=1h`
- **THEN** the response is a list of usage rows for that skill in the last hour, capped at 1000 rows by default

#### Scenario: Group by account

- **WHEN** the user calls `GET /v1/usage?group_by=account&since=24h`
- **THEN** the response is a list of `{account_id, account_label, request_count, error_count, avg_latency_ms}` objects

### Requirement: Default Bind Address

The system SHALL default-bind the HTTP daemon to `127.0.0.1:8787` and SHALL allow override via `ROUTE_FORGE_HOST` and `ROUTE_FORGE_PORT`.

#### Scenario: Default bind

- **WHEN** the daemon starts without env overrides
- **THEN** it binds to `127.0.0.1:8787`

#### Scenario: Override bind

- **WHEN** the daemon starts with `ROUTE_FORGE_PORT=9999`
- **THEN** it binds to `127.0.0.1:9999`

### Requirement: Local-Only by Default

The system SHALL refuse to bind to a non-loopback address unless `ROUTE_FORGE_ALLOW_PUBLIC=1` is set explicitly.

#### Scenario: Public bind refused

- **WHEN** the daemon is asked to bind to `0.0.0.0` without the override
- **THEN** the daemon exits with code 2 and a clear error message

## ADDED Requirements

### Requirement: Skill Manage Endpoints

The system SHALL expose `POST /v1/skills/manage/reload` and `GET /v1/skills/manage` for plugin lifecycle management.

#### Scenario: Reload skills

- **WHEN** the TUI or a client calls `POST /v1/skills/manage/reload`
- **THEN** the registry clears, re-scans every source, and returns the diff payload `{"added": [...], "removed": [...], "updated": [...]}` with HTTP 200

#### Scenario: List managed skills

- **WHEN** the TUI calls `GET /v1/skills/manage?source=plugin`
- **THEN** the response is the list of skills with `source='plugin'`, including the plugin manifest path and module path

### Requirement: Account Manage Endpoints

The system SHALL expose `POST /v1/accounts/manage/toggle` and `POST /v1/accounts/manage/disable` to flip the `enabled` flag without deleting the account.

#### Scenario: Toggle account

- **WHEN** the TUI calls `POST /v1/accounts/manage/toggle` with `{"account_id": 5}`
- **THEN** the account's `enabled` flag is inverted, persisted, and `account.disabled` or `account.recovered` is published accordingly

### Requirement: SSE Events Endpoint

The system SHALL expose `GET /v1/events` as a `text/event-stream` HTTP endpoint publishing the events described in the `events` capability.

#### Scenario: SSE stream

- **WHEN** a client opens `GET /v1/events`
- **THEN** the response has `Content-Type: text/event-stream` and streams JSON-encoded event frames until the client disconnects

#### Scenario: Heartbeat

- **WHEN** no events are published for 15 seconds
- **THEN** the server sends an SSE comment line `: keepalive\n\n`

### Requirement: Provider-Group Dispatch

The router MUST resolve the candidate account set using the skill's `provider_group` when present.

#### Scenario: Skill with provider_group

- **WHEN** a skill declares `provider_group='scrape'`
- **THEN** the candidate set is the subset of accounts whose `tags` list contains `'scrape'`
- **AND** accounts without that tag are excluded regardless of `provider`

#### Scenario: No accounts match

- **WHEN** no account has the required tag
- **THEN** `Router.dispatch` raises `RouterError("no_accounts_for_group")` and the HTTP layer returns HTTP 400 with `{"error": "no_accounts_for_group", "skill": "...", "group": "..."}`

#### Scenario: Skill without provider_group

- **WHEN** a skill declares `provider_group=None`
- **THEN** the candidate set is every account whose `provider` matches the skill's `provider` (preserves `bootstrap-core` behavior)
