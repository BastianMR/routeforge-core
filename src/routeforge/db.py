"""SQLite connection helper and schema bootstrap."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  label TEXT NOT NULL,
  api_key_encrypted BLOB NOT NULL,
  base_url TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TEXT,
  UNIQUE(provider, label)
);

CREATE TABLE IF NOT EXISTS usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER,
  skill TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status_code INTEGER,
  latency_ms INTEGER,
  error TEXT,
  FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_usage_provider_skill ON usage_log(skill);
CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts(provider);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection in WAL mode and apply the schema."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
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
