# usage-tracking

## Purpose

Every skill dispatch produces a usage event persisted to SQLite. Operators query recent usage via HTTP and receive aggregate updates via SSE. The data powers both the TUI's Usage tab and any external observability tooling.

## ADDED Requirements

### Requirement: Write on every dispatch

The router MUST write one row to `usage_log` for every dispatch, including failures.

#### Scenario: Successful dispatch logged

- **WHEN** `Router.dispatch("firecrawl/scrape", {...})` completes with status 200
- **THEN** one row is inserted into `usage_log` with `status="success"`, `latency_ms=<measured>`, `account_id=<chosen>`

#### Scenario: Failed dispatch logged

- **WHEN** `Router.dispatch` raises `SkillError`
- **THEN** one row is inserted with `status="error_4xx"` (or `error_5xx` / `error_network` as appropriate), `latency_ms=<measured>`, and `error=<message>`

### Requirement: Schema fields

The `usage_log` row MUST include: `id`, `ts`, `skill_name`, `account_id` (nullable), `status`, `latency_ms`, `provider_group`, `tags` (JSON array of the resolved accounts' tags), `error` (nullable).

#### Scenario: Row shape

- **WHEN** a dispatch completes
- **THEN** the row written has all fields populated, with `account_id` set to `-1` for skills that do not require an account

### Requirement: Query API

The HTTP endpoint `GET /v1/usage` MUST support filtering and grouping.

#### Scenario: Filter by skill

- **WHEN** the user calls `GET /v1/usage?skill=firecrawl/scrape&since=1h`
- **THEN** the response is a list of usage rows for that skill in the last hour, capped at 1000 rows by default

#### Scenario: Group by account

- **WHEN** the user calls `GET /v1/usage?group_by=account&since=24h`
- **THEN** the response is a list of `{account_id, account_label, request_count, error_count, avg_latency_ms}` objects

#### Scenario: Group by skill

- **WHEN** the user calls `GET /v1/usage?group_by=skill&since=24h`
- **THEN** the response is a list of `{skill_name, request_count, error_count, avg_latency_ms, top_account_id}` objects

### Requirement: Periodic rollup

A background task MUST roll up `usage_log` into `usage_daily` every 5 minutes.

#### Scenario: Rollup runs

- **WHEN** 5 minutes have passed since the last rollup
- **THEN** the system groups all `usage_log` rows from the last 24 hours by `(day, skill_name, account_id, status)`, computes counts and latency stats, and UPSERTs into `usage_daily`

### Requirement: Retention

The system MUST keep at least 30 days of `usage_log` and 1 year of `usage_daily` by default.

#### Scenario: Manual cleanup

- **WHEN** the user runs `routeforge usage prune --older-than 90d`
- **THEN** `usage_log` rows older than 90 days are deleted in a single transaction

### Requirement: Privacy

`usage_log` MUST NOT store raw API keys, request bodies, or response bodies. Only metadata (counts, latency, status, error message) is stored.

#### Scenario: Bodies never written

- **WHEN** a dispatch completes
- **THEN** the database write contains no field whose value is the request or response body
