# Mcp Server Specification

## Purpose

Define the MCP server surface: transports (stdio and optional streamable-HTTP), the tools advertised (`list_skills`, `call_skill`, `list_accounts`, `get_usage`, plus the new `reload_skills`, `list_plugins`, `tag_account`), the `listChanged` capability for live plugin reloads, and the rule that no TCP port is bound unless the streamable-HTTP transport is explicitly enabled.

## MODIFIED Requirements

### Requirement: MCP Server Speaks stdio Transport

The system SHALL run an MCP server over stdio (JSON-RPC over stdin/stdout) when invoked via `routeforge mcp`.

#### Scenario: stdio startup

- **WHEN** a user runs `routeforge mcp`
- **THEN** the daemon initializes the official `mcp` Python SDK in stdio mode and blocks on stdin

### Requirement: list_skills Tool

The system SHALL expose a `list_skills` tool that returns every registered skill with its name, source, provider, description, JSON schema, `provider_group`, and `requires_account`.

#### Scenario: Listing all skills

- **WHEN** an MCP client calls `list_skills()`
- **THEN** the response is `{"skills": [{"name": "echo", "source": "builtin", "provider": "echo", "description": "...", "schema": {...}, "provider_group": null, "requires_account": false}, ...]}`

### Requirement: call_skill Tool

The system SHALL expose a `call_skill` tool that takes `name: str`, `args: dict`, and an optional `account_label: str | None`, dispatches to the router, and returns the result.

#### Scenario: Successful call

- **WHEN** an MCP client calls `call_skill(name="echo", args={"x": 1})`
- **THEN** the response is `{"result": {"x": 1}}`

#### Scenario: Pin to a specific account

- **WHEN** an MCP client calls `call_skill(name="firecrawl/scrape", args={...}, account_label="fc1")`
- **THEN** the router bypasses round-robin and uses the account whose `label` is `"fc1"`
- **AND** if the named account is disabled or does not exist, the response is `{"error": "account_not_found", "label": "fc1"}` with `isError: true`

#### Scenario: Skill failure

- **WHEN** an MCP client calls `call_skill(name="firecrawl/scrape", args={...})` and the upstream returns 429
- **THEN** the response is `{"error": "upstream 429"}` with `isError: true`, the account is marked cooled, and `account.cooldown_started` is published

### Requirement: list_accounts Tool

The system SHALL expose a `list_accounts` tool that returns account metadata without leaking API keys.

#### Scenario: Listing by provider

- **WHEN** an MCP client calls `list_accounts(provider="firecrawl")`
- **THEN** the response is `{"accounts": [{"id": 1, "label": "personal-1", "tags": [], "enabled": true, "last_used_at": null}, ...]}`

#### Scenario: Listing all providers

- **WHEN** an MCP client calls `list_accounts(provider=None)`
- **THEN** the response is `{"accounts": {"firecrawl": [...], "tavily": [...]}}`

### Requirement: get_usage Tool

The system SHALL expose a `get_usage` tool that returns aggregated usage statistics.

#### Scenario: Usage summary

- **WHEN** an MCP client calls `get_usage(provider="firecrawl")`
- **THEN** the response is `{"provider": "firecrawl", "calls": 5, "errors": 1, "by_account": [{"account_id": 1, "calls": 5, "errors": 1}]}`

### Requirement: No Network Exposure

The system SHALL NOT bind any TCP port when running in MCP mode and the streamable-HTTP transport is not enabled.

#### Scenario: stdio mode bind check

- **WHEN** the daemon is running in MCP mode and `ROUTE_FORGE_MCP_HTTP_PORT` is not set
- **THEN** no socket is open on the configured HTTP host/port

### Requirement: MCP Tools Are Discoverable

The system SHALL advertise its tools in the MCP `tools/list` response with stable names.

#### Scenario: Tool discovery

- **WHEN** a client sends `tools/list`
- **THEN** the response contains exactly seven tool names: `list_skills`, `call_skill`, `list_accounts`, `get_usage`, `reload_skills`, `list_plugins`, `tag_account`

## ADDED Requirements

### Requirement: listChanged Capability

The MCP server MUST declare `capabilities.tools.listChanged = true` so clients know they can subscribe to live updates.

#### Scenario: Capability declared

- **WHEN** an MCP client initializes a session
- **THEN** the server's response includes `capabilities.tools.listChanged = true`

### Requirement: notifications/tools/list_changed on Reload

The server MUST send `notifications/tools/list_changed` to every connected MCP session when `SkillRegistry.reload()` runs.

#### Scenario: Reload notification

- **WHEN** the user runs `routeforge skills reload`
- **AND** two MCP clients are connected
- **THEN** both clients receive a `notifications/tools/list_changed` frame
- **AND** a subsequent `tools/list` from either client returns the updated tool set including any newly loaded plugin

### Requirement: reload_skills Tool

The system SHALL expose a `reload_skills` tool that triggers `SkillRegistry.reload()` and returns the diff payload.

#### Scenario: Reload via MCP

- **WHEN** an MCP client calls `reload_skills()`
- **THEN** the response is `{"added": [...], "removed": [...], "updated": [...]}`

### Requirement: list_plugins Tool

The system SHALL expose a `list_plugins` tool that returns every loaded plugin with its source path, module path, enabled flag, and last loaded timestamp.

#### Scenario: List plugins

- **WHEN** an MCP client calls `list_plugins()`
- **THEN** the response is `{"plugins": [{"name": "web-scrape", "source": "plugin", "module": "my_skills.scraper", "manifest_path": "~/.routeforge/plugins/web-scrape.toml", "enabled": true, "loaded_at": "2026-09-25T12:00:00Z"}, ...]}`

### Requirement: tag_account Tool

The system SHALL expose a `tag_account` tool that adds or removes tags on an account identified by its label.

#### Scenario: Add tags

- **WHEN** an MCP client calls `tag_account(label="fc1", add=["scrape", "web"])`
- **THEN** the account's `tags` field becomes the union of its previous tags and `["scrape", "web"]`, the change is persisted, and `account.disabled` (or `account.recovered`) is NOT published (tags are not lifecycle events)

### Requirement: Optional Streamable-HTTP Transport

The system MUST support an optional streamable-HTTP transport at the path `/mcp` when `ROUTE_FORGE_MCP_HTTP_PORT` is set.

#### Scenario: HTTP transport enabled

- **WHEN** `ROUTE_FORGE_MCP_HTTP_PORT=8788` is set
- **THEN** the server binds to `127.0.0.1:8788/mcp` and accepts MCP JSON-RPC over HTTP
- **AND** stdio transport remains available

#### Scenario: HTTP transport disabled

- **WHEN** `ROUTE_FORGE_MCP_HTTP_PORT` is not set
- **THEN** only stdio transport is available and no TCP port is bound

#### Scenario: HTTP transport bearer token

- **WHEN** both `ROUTE_FORGE_MCP_HTTP_PORT` and `ROUTE_FORGE_MCP_HTTP_TOKEN` are set
- **THEN** every HTTP MCP request MUST include `Authorization: Bearer <token>` or be rejected with HTTP 401
