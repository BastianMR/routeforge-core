# events

## Purpose

The event bus is an in-process pub/sub used by the core to publish state changes. External clients consume events via the SSE endpoint. The bus is fire-and-forget; slow subscribers drop events with a counter increment.

## ADDED Requirements

### Requirement: In-process pub/sub

The core MUST provide an `EventBus` with `publish(event)` and `subscribe() -> asyncio.Queue` semantics.

#### Scenario: Subscriber receives event

- **WHEN** a subscriber calls `subscribe()`
- **AND** another coroutine calls `publish(AccountCooldownStarted(account_id=5))`
- **THEN** the subscriber's queue receives the event within 100ms

#### Scenario: Multiple subscribers

- **WHEN** two subscribers are registered
- **AND** one event is published
- **THEN** both subscribers receive the event

### Requirement: Event types

The bus MUST publish these event types with the listed payloads:

| Event | Payload |
|---|---|
| `account.cooldown_started` | `{account_id, until, reason}` |
| `account.recovered` | `{account_id}` |
| `account.disabled` | `{account_id}` |
| `skill.reloaded` | `{added: [name], removed: [name], updated: [name]}` |
| `usage.tick` | `{window: "1m", requests: N, errors: M, ts: ISO8601}` |
| `call.completed` | `{skill, account_id, status, latency_ms, ts: ISO8601}` |

#### Scenario: Cooldown event emitted on 429

- **WHEN** an account returns HTTP 429
- **THEN** `account.cooldown_started` is published with `until=<now+cooldown_seconds>`

#### Scenario: Recovery event emitted after success

- **WHEN** an account that was in cooldown successfully completes a call
- **THEN** `account.recovered` is published with the `account_id`

### Requirement: Ring buffer

The bus MUST keep the last 100 events in a ring buffer for late subscribers.

#### Scenario: Buffer size

- **WHEN** more than 100 events are published
- **THEN** only the most recent 100 are retained; older events are dropped

#### Scenario: Buffer size configurable

- **WHEN** `ROUTE_FORGE_EVENT_BUFFER_SIZE=500` is set
- **THEN** the buffer holds the last 500 events

### Requirement: SSE endpoint

The core MUST expose `GET /v1/events` as a `text/event-stream` HTTP endpoint.

#### Scenario: Stream connection

- **WHEN** a client opens `GET /v1/events`
- **THEN** the response has `Content-Type: text/event-stream` and stays open until the client disconnects

#### Scenario: Event framing

- **WHEN** an event is published
- **THEN** every connected SSE client receives a frame like:
  ```
  event: account.cooldown_started
  id: 42
  data: {"account_id": 5, "until": "2026-09-25T12:34:56Z", "reason": "429"}

  ```

#### Scenario: Heartbeat

- **WHEN** no events are published for 15 seconds
- **THEN** the server sends an SSE comment line `: keepalive\n\n` to keep proxies and clients from closing the connection

#### Scenario: Replay on reconnect

- **WHEN** a client reconnects with `Last-Event-ID`
- **THEN** the server replays any events in the ring buffer with ids greater than the one provided

### Requirement: Loopback binding

The SSE endpoint MUST follow the same loopback binding rules as the rest of the HTTP API (see `secrets` capability in `bootstrap-core`).

#### Scenario: Refuse non-loopback without allow-public

- **WHEN** the SSE endpoint is requested from a non-loopback address
- **AND** `ROUTE_FORGE_ALLOW_PUBLIC` is not set
- **THEN** the connection is refused with HTTP 403

### Requirement: No persistence

The event bus MUST NOT write events to SQLite directly. Persistence happens through `usage-tracking` for `call.completed` and through `plugins` for plugin state.

#### Scenario: Events not in SQLite

- **WHEN** an event is published
- **THEN** no row is inserted into `usage_log` from the bus itself; only the dispatcher writes usage rows
