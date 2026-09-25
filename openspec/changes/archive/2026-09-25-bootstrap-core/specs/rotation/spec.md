## ADDED Requirements

### Requirement: Round-Robin Account Selection
The system SHALL select accounts in strict round-robin order per provider, skipping any account that is currently in cooldown.

#### Scenario: Sequential selection
- **WHEN** the pool for `firecrawl` has 3 accounts A, B, C and 3 calls are made in sequence
- **THEN** the calls use A, B, C respectively

#### Scenario: Skip cooled account
- **WHEN** account B is in cooldown and a call arrives
- **THEN** the daemon uses C (the next non-cooled account) and increments the cursor by 1 (skipping B)

#### Scenario: All accounts cooled
- **WHEN** all accounts of a provider are in cooldown
- **THEN** `acquire()` returns `None` and the daemon returns HTTP 503 with `Retry-After`

### Requirement: Cursor Is Process-Local and Async-Safe
The system SHALL guard the cursor with `asyncio.Lock` per pool to prevent concurrent acquire() from advancing the cursor twice for a single request.

#### Scenario: 100 concurrent acquires
- **WHEN** 100 concurrent `acquire()` calls hit a 3-account pool
- **THEN** each account is handed out exactly once per cycle and no account is skipped or duplicated

### Requirement: Cooldown Activation on Upstream Failures
The system SHALL put an account into cooldown when the upstream returns HTTP 429, 402, or 5xx.

#### Scenario: 429 from upstream
- **WHEN** a skill call returns HTTP 429
- **THEN** the account is marked cooled for `cooldown_seconds` (default 60)

#### Scenario: 200 from upstream
- **WHEN** a skill call returns HTTP 2xx
- **THEN** the account's cooldown is cleared and it is marked available again

### Requirement: Cooldown Duration Configurable Per Provider
The system SHALL read `cooldown_seconds` per provider from the config (default 60) and SHALL expire the cooldown automatically after that duration has elapsed.

#### Scenario: Default cooldown
- **WHEN** a provider has no `cooldown_seconds` override
- **THEN** the daemon uses 60 seconds

#### Scenario: Cooldown expires
- **WHEN** `cooldown_seconds` have elapsed since the failure
- **THEN** `acquire()` returns the previously cooled account

### Requirement: Usage Logging
The system SHALL write a row to `usage_log` for every skill call, recording account_id, skill, timestamp, status code, latency_ms, and error (if any).

#### Scenario: Successful call logged
- **WHEN** a skill call returns 200 in 350ms
- **THEN** `usage_log` receives `(account_id, skill_name, ts, 200, 350, NULL)`

#### Scenario: Failed call logged
- **WHEN** a skill call returns 429
- **THEN** `usage_log` receives `(account_id, skill_name, ts, 429, latency, "upstream 429")`

### Requirement: Concurrent In-Flight Cap
The system SHALL allow at most one in-flight call per account at any time; concurrent calls to the same account SHALL queue (await) until the previous one completes.

#### Scenario: Two concurrent calls to the same account
- **WHEN** two concurrent calls both target the same account
- **THEN** the second call awaits the first; both succeed sequentially