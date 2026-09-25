# Mcp Server Specification

## Purpose
Define the MCP server surface: transport (stdio), the four tools advertised (`list_skills`, `call_skill`, `list_accounts`, `get_usage`), and the rule that no TCP port is bound in MCP mode.

## Requirements

### Requirement: MCP Server Speaks stdio Transport
The system SHALL run an MCP server over stdio (JSON-RPC over stdin/stdout) when invoked via `routeforge mcp`.

#### Scenario: stdio startup
- **WHEN** a user runs `routeforge mcp`
- **THEN** the daemon initializes the official `mcp` Python SDK in stdio mode and blocks on stdin

### Requirement: list_skills Tool
The system SHALL expose a `list_skills` tool that returns every registered skill with its name, provider, description, and JSON schema.

#### Scenario: Listing all skills
- **WHEN** an MCP client calls `list_skills()`
- **THEN** the response is `{"skills": [{"name": "echo", "provider": "echo", "description": "...", "schema": {...}}, ...]}`

### Requirement: call_skill Tool
The system SHALL expose a `call_skill` tool that takes `name: str` and `args: dict`, dispatches to the router, and returns the result.

#### Scenario: Successful call
- **WHEN** an MCP client calls `call_skill(name="echo", args={"x": 1})`
- **THEN** the response is `{"result": {"x": 1}}`

#### Scenario: Skill failure
- **WHEN** an MCP client calls `call_skill(name="firecrawl/scrape", args={...})` and the upstream returns 429
- **THEN** the response is `{"error": "upstream 429"}` and the account is marked cooled

### Requirement: list_accounts Tool
The system SHALL expose a `list_accounts` tool that returns account metadata without leaking API keys.

#### Scenario: Listing by provider
- **WHEN** an MCP client calls `list_accounts(provider="firecrawl")`
- **THEN** the response is `{"accounts": [{"id": 1, "label": "personal-1", "last_used_at": null}, ...]}`

#### Scenario: Listing all providers
- **WHEN** an MCP client calls `list_accounts(provider=None)`
- **THEN** the response is `{"accounts": {"firecrawl": [...], "tavily": [...]}}`

### Requirement: get_usage Tool
The system SHALL expose a `get_usage` tool that returns aggregated usage statistics.

#### Scenario: Usage summary
- **WHEN** an MCP client calls `get_usage(provider="firecrawl")`
- **THEN** the response is `{"provider": "firecrawl", "calls": 5, "errors": 1, "by_account": [{"account_id": 1, "calls": 5, "errors": 1}]}`

### Requirement: No Network Exposure
The system SHALL NOT bind any TCP port when running in MCP mode.

#### Scenario: stdio mode bind check
- **WHEN** the daemon is running in MCP mode
- **THEN** no socket is open on the configured HTTP host/port

### Requirement: MCP Tools Are Discoverable
The system SHALL advertise all four tools (`list_skills`, `call_skill`, `list_accounts`, `get_usage`) in the MCP `tools/list` response with stable names.

#### Scenario: Tool discovery
- **WHEN** a client sends `tools/list`
- **THEN** the response contains exactly the four tool names above