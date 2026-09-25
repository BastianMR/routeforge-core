## ADDED Requirements

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
The system SHALL expose `GET /v1/skills` that returns the list of registered skills.

#### Scenario: Listing registered skills
- **WHEN** a client GETs `/v1/skills`
- **THEN** the daemon returns `[{"name": "echo", "provider": "echo", "description": "...", "schema": {...}}, ...]`

### Requirement: Accounts Listing Endpoint
The system SHALL expose `GET /v1/accounts` that returns account metadata (never the raw API key).

#### Scenario: Listing accounts
- **WHEN** a client GETs `/v1/accounts`
- **THEN** the daemon returns `{"echo": [{"id": 1, "label": "x", "last_used_at": null}, ...]}` grouped by provider

### Requirement: Usage Endpoint
The system SHALL expose `GET /v1/usage?provider=<p>` that returns usage stats aggregated by account and skill.

#### Scenario: Filtered usage
- **WHEN** a client GETs `/v1/usage?provider=firecrawl`
- **THEN** the daemon returns `{"firecrawl": {"accounts": [{"id": 1, "calls": 5, "errors": 0}], "skills": [...]}}`

### Requirement: Default Bind Address
The system SHALL default-bind the HTTP daemon to `127.0.0.1:8080` and SHALL allow override via `ROUTE_FORGE_HOST` and `ROUTE_FORGE_PORT`.

#### Scenario: Default bind
- **WHEN** the daemon starts without env overrides
- **THEN** it binds to `127.0.0.1:8080`

#### Scenario: Override bind
- **WHEN** the daemon starts with `ROUTE_FORGE_PORT=9999`
- **THEN** it binds to `127.0.0.1:9999`

### Requirement: Local-Only by Default
The system SHALL refuse to bind to a non-loopback address unless `ROUTE_FORGE_ALLOW_PUBLIC=1` is set explicitly.

#### Scenario: Public bind refused
- **WHEN** the daemon is asked to bind to `0.0.0.0` without the override
- **THEN** the daemon exits with code 2 and a clear error message