## ADDED Requirements

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
The system SHALL discover every skill under `routeforge.skills.builtin` at startup and register them; no manual registration call is required.

#### Scenario: Boot discovery
- **WHEN** the daemon starts
- **THEN** every class subclassing `Skill` inside `routeforge.skills.builtin` is registered with its declared `name`

### Requirement: Skill Receives an Account and an HTTP Client
The system SHALL call `skill.execute(account, args, http)` where `account` exposes at minimum `api_key`, `base_url`, and `metadata`; `http` is a shared `httpx.AsyncClient`.

#### Scenario: Skill makes upstream call
- **WHEN** the skill calls `http.post(...)` with `headers={"Authorization": f"Bearer {account.api_key}"}`
- **THEN** the upstream receives the correct bearer token

### Requirement: Skill Errors Surface to Caller
The system SHALL propagate `SkillError` (and its subclasses) to the caller as `{"error": "<message>"}` with HTTP 502.

#### Scenario: Skill raises SkillError
- **WHEN** `skill.execute()` raises `SkillError("upstream 503")`
- **THEN** the daemon returns HTTP 502 with `{"error": "upstream 503"}` and the account is NOT marked cooled

### Requirement: Two Built-in Skills Ship in v1
The system SHALL ship `echo` (returns args unchanged) and `firecrawl/scrape` (POSTs to the configured base_url) as built-in skills.

#### Scenario: Echo skill
- **WHEN** a client calls `echo` with `{"args": {"x": 1}}`
- **THEN** the response is `{"result": {"x": 1}}`

#### Scenario: Firecrawl scrape skill
- **WHEN** a client calls `firecrawl/scrape` with `{"args": {"url": "https://example.com", "formats": ["markdown"]}}`
- **THEN** the skill POSTs to `{account.base_url}/v1/scrape` and returns the upstream JSON