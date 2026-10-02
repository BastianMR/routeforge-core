"""SQLite connection helper and idempotent schema migrations."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

# Bootstrap schema. CREATE TABLE IF NOT EXISTS means this is a no-op on a
# database created by an earlier version; `migrate()` upgrades those.
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  label TEXT NOT NULL,
  api_key_encrypted BLOB NOT NULL,
  base_url TEXT,
  metadata_json TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TEXT,
  UNIQUE(provider, label)
);

CREATE TABLE IF NOT EXISTS usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER,
  skill_name TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  provider_group TEXT,
  tags TEXT,
  error TEXT,
  FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS usage_daily (
  day TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  account_id INTEGER NOT NULL,
  status TEXT NOT NULL,
  request_count INTEGER NOT NULL,
  error_count INTEGER NOT NULL,
  avg_latency_ms REAL NOT NULL,
  p95_latency_ms REAL NOT NULL,
  PRIMARY KEY (day, skill_name, account_id, status)
);

CREATE TABLE IF NOT EXISTS plugins (
  name TEXT PRIMARY KEY,
  source TEXT NOT NULL CHECK(source IN ('builtin', 'plugin', 'manifest')),
  module_path TEXT,
  attr TEXT,
  manifest_path TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  error TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_usage_provider_skill ON usage_log(skill_name);
CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts(provider);
CREATE INDEX IF NOT EXISTS idx_usage_log_skill_time ON usage_log(skill_name, ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_log_account_time ON usage_log(account_id, ts DESC);
"""

# (table, column, DDL fragment) applied only when the column is absent.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("accounts", "tags", "TEXT NOT NULL DEFAULT '[]'"),
    ("accounts", "enabled", "INTEGER NOT NULL DEFAULT 1"),
    ("usage_log", "skill_name", "TEXT"),
    ("usage_log", "status", "TEXT"),
    ("usage_log", "provider_group", "TEXT"),
    ("usage_log", "tags", "TEXT"),
    ("plugins", "attr", "TEXT"),
    ("plugins", "error", "TEXT"),
)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the column names of `table` (empty set when the table is absent)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema.

    Safe to call on every startup: each step is guarded by an existence check.
    Rows written by an earlier version are preserved and backfilled.
    """
    conn.executescript(SCHEMA)

    for table, column, ddl in ADDED_COLUMNS:
        if table not in _tables(conn):
            continue
        if column in columns(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    _backfill_usage_log(conn)
    conn.executescript(INDEXES)


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def _backfill_usage_log(conn: sqlite3.Connection) -> None:
    """Copy the legacy `skill` / `status_code` columns into `skill_name` / `status`.

    Only touches databases that still carry the legacy columns, so a fresh
    database is never written to.
    """
    legacy = columns(conn, "usage_log")
    if "skill" not in legacy or "status_code" not in legacy:
        return
    conn.execute(
        """
        UPDATE usage_log SET skill_name = skill WHERE skill_name IS NULL
        """
    )
    conn.execute(
        """
        UPDATE usage_log SET status =
          CASE
            WHEN status_code IS NULL THEN 'success'
            WHEN status_code < 400 THEN 'success'
            WHEN status_code < 500 THEN 'error_4xx'
            ELSE 'error_5xx'
          END
        WHERE status IS NULL
        """
    )


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection in WAL mode and apply the schema.

    `check_same_thread=False` is required because FastAPI serves sync endpoints
    on a worker threadpool while the event loop writes usage rows. WAL plus
    `isolation_level=None` keeps the concurrent access safe.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a BEGIN/COMMIT block with automatic rollback on error."""
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
