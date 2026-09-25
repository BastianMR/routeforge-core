## ADDED Requirements

### Requirement: API Keys Encrypted at Rest
The system SHALL encrypt every API key with Fernet (AES-128-CBC + HMAC-SHA256) before writing it to the `accounts` table.

#### Scenario: Adding an account
- **WHEN** a user runs `routeforge accounts add firecrawl --key fc-xxx`
- **THEN** the daemon stores `Fernet.encrypt(b"fc-xxx")` in `accounts.api_key_encrypted`

#### Scenario: Reading an account
- **WHEN** the daemon loads an account from the DB
- **THEN** it calls `Fernet.decrypt(ciphertext)` to obtain the plaintext key for the upstream call
- **AND** the plaintext key is held in memory only for the duration of the call

### Requirement: Master Key From Environment
The system SHALL read the master encryption key from the environment variable `ROUTE_FORGE_MASTER_KEY` and SHALL refuse to start without it.

#### Scenario: Missing master key
- **WHEN** the daemon starts and `ROUTE_FORGE_MASTER_KEY` is unset
- **THEN** the daemon exits with code 3 and prints `error: ROUTE_FORGE_MASTER_KEY is required`

#### Scenario: Malformed master key
- **WHEN** the env var is set but is not a valid Fernet key (not 32 url-safe base64 bytes)
- **THEN** the daemon exits with code 3 and prints `error: ROUTE_FORGE_MASTER_KEY is not a valid Fernet key`

### Requirement: Key Generation Helper
The system SHALL expose `routeforge secrets generate` that prints a freshly generated Fernet key to stdout.

#### Scenario: Generate key
- **WHEN** a user runs `routeforge secrets generate`
- **THEN** the daemon prints a single Fernet key (44 url-safe base64 characters) and exits 0

### Requirement: Master Key Never Logged or Echoed
The system SHALL never write the master key, decrypted API keys, or any portion thereof to logs, error messages, or HTTP responses.

#### Scenario: Encryption failure
- **WHEN** `Fernet.decrypt()` raises `InvalidToken`
- **THEN** the daemon returns a generic `error: decryption failed` message without echoing any ciphertext or attempted plaintext

### Requirement: Ciphertext Round-Trip
The system SHALL guarantee that any ciphertext produced by `Secrets.encrypt(plaintext)` can be decrypted back to the same `plaintext` by `Secrets.decrypt`.

#### Scenario: Round-trip
- **WHEN** the test encrypts `"hello"` then decrypts the result
- **THEN** the decrypted value equals `"hello"`