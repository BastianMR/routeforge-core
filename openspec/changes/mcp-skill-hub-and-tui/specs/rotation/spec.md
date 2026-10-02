# Rotation Specification

## Purpose

Define the round-robin account selection rules, cooldown triggers, and per-account concurrency limits that routeforge-core uses to distribute requests across N accounts of the same upstream provider.

## MODIFIED Requirements

### Requirement: Round-Robin Account Selection

The system SHALL select accounts in strict round-robin order over the candidate set passed to `RoundRobinPool.pick(candidates)`, skipping any account that is currently in cooldown. The candidate set is constructed by the router based on the skill's `provider_group` or, if absent, the skill's `provider`.

#### Scenario: Sequential selection

- **WHEN** the pool for `firecrawl` has 3 accounts A, B, C and 3 calls are made in sequence
- **THEN** the calls use A, B, C respectively

#### Scenario: Sequential selection with provider-group filtering

- **WHEN** the router resolves a skill with `provider_group='scrape'`
- **AND** the accounts tagged `scrape` are A, B, C
- **AND** 3 calls are made in sequence
- **THEN** the calls use A, B, C respectively

#### Scenario: Skip cooled account

- **WHEN** account B is in cooldown and a call arrives
- **THEN** the daemon uses C (the next non-cooled account) and increments the cursor by 1 (skipping B)

#### Scenario: Skill without provider_group

- **WHEN** the router resolves a skill whose `provider_group` is `None`
- **THEN** the candidate set is every account whose `provider` equals the skill's `provider` (the existing 1-to-1 behavior from `bootstrap-core`)

#### Scenario: All accounts cooled

- **WHEN** all accounts of a provider are in cooldown
- **THEN** `pick()` returns `None` and the daemon returns HTTP 503 with `Retry-After`

### Requirement: Cursor Is Process-Local and Async-Safe

The system SHALL guard the cursor with `asyncio.Lock` per pool to prevent concurrent `pick()` from advancing the cursor twice for a single request.

#### Scenario: 100 concurrent acquires

- **WHEN** 100 concurrent `pick()` calls hit a 3-account pool
- **THEN** each account is handed out exactly once per cycle and no account is skipped or duplicated

### Requirement: Cooldown Activation on Upstream Failures

The system SHALL put an account into cooldown when the upstream returns HTTP 429, 402, or 5xx, and SHALL publish an `account.cooldown_started` event with `{account_id, until, reason}`.

#### Scenario: 429 from upstream

- **WHEN** a skill call returns HTTP 429
- **THEN** the account is marked cooled for `cooldown_seconds` (default 60)
- **AND** `account.cooldown_started` is published with `reason='429'`

#### Scenario: 200 from upstream

- **WHEN** a skill call returns HTTP 2xx
- **THEN** the account's cooldown is cleared, it is marked available again, and `account.recovered` is published if the account was previously in cooldown

### Requirement: Cooldown Duration Configurable Per Provider

The system SHALL read `cooldown_seconds` per provider from the config (default 60) and SHALL expire the cooldown automatically after that duration has elapsed.

#### Scenario: Default cooldown

- **WHEN** a provider has no `cooldown_seconds` override
- **THEN** the daemon uses 60 seconds

#### Scenario: Cooldown expires

- **WHEN** `cooldown_seconds` have elapsed since the failure
- **THEN** `pick()` returns the previously cooled account

### Requirement: Usage Logging

The system SHALL write a row to `usage_log` for every skill call, recording `account_id`, `skill_name`, `ts`, `status`, `latency_ms`, `provider_group`, `tags` (JSON array of resolved accounts' tags), and `error` (if any).

#### Scenario: Successful call logged

- **WHEN** a skill call returns 200 in 350ms
- **THEN** `usage_log` receives `(account_id, skill_name, ts, 'success', 350, <provider_group>, <tags_json>, NULL)`

#### Scenario: Failed call logged

- **WHEN** a skill call returns 429
- **THEN** `usage_log` receives `(account_id, skill_name, ts, 'error_4xx', latency, <provider_group>, <tags_json>, 'upstream 429')`

### Requirement: Concurrent In-Flight Cap

The system SHALL allow at most one in-flight call per account at any time; concurrent calls to the same account SHALL queue (await) until the previous one completes.

#### Scenario: Two concurrent calls to the same account

- **WHEN** two concurrent calls both target the same account
- **THEN** the second call awaits the first; both succeed sequentially

## ADDED Requirements

### Requirement: Pool Snapshot for TUI

`RoundRobinPool.snapshot()` MUST return a per-account dict with `{state, cooldown_until, consecutive_failures, last_used_at, last_error}` for every account in the pool. The snapshot is consumed by the TUI's Accounts tab and the SSE event stream.

#### Scenario: Snapshot reflects state

- **WHEN** the TUI polls the snapshot after a cooldown event
- **THEN** the affected account row shows `state='cooldown'`, `cooldown_until=<future_ts>`, `consecutive_failures>=1`

### Requirement: Tag-Based Filtering Happens Before Round-Robin

The router MUST construct the candidate set before calling `RoundRobinPool.pick`. The pool itself MUST NOT know about tags; tags are a routing-layer concern.

#### Scenario: Pool only sees the candidate set

- **WHEN** the router resolves a skill with `provider_group='scrape'` and 5 total accounts exist (3 tagged `scrape`, 2 with no tags)
- **THEN** `RoundRobinPool.pick` receives only the 3 tagged accounts; the 2 untagged accounts are invisible to that call

### Requirement: Account Disabled Flag

`Account.enabled: bool = True` MUST be honored by the pool: a disabled account is treated as if in cooldown indefinitely until re-enabled.

#### Scenario: Disabled account is skipped

- **WHEN** the TUI toggles an account's enabled flag to false
- **AND** a call resolves to a skill using that provider or provider_group
- **THEN** the disabled account is skipped as a candidate
- **AND** `account.disabled` is published
