"""Tests for idempotent schema migrations."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from routeforge.db import columns, connect, migrate

LEGACY_SCHEMA = """
CREATE TABLE accounts (
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

CREATE TABLE usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER,
  skill TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status_code INTEGER,
  latency_ms INTEGER,
  error TEXT,
  FOREIGN KEY(account_id) REFERENCES accounts(id)
);
"""


@pytest.fixture
def legacy_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO accounts (provider, label, api_key_encrypted) VALUES ('p', 'a', X'00')"
    )
    conn.execute(
        "INSERT INTO usage_log (account_id, skill, status_code, latency_ms, error)"
        " VALUES (1, 'echo', 200, 12, NULL)"
    )
    conn.execute(
        "INSERT INTO usage_log (account_id, skill, status_code, latency_ms, error)"
        " VALUES (1, 'echo', 429, 34, 'upstream 429')"
    )
    conn.commit()
    conn.close()
    try:
        yield path
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def test_fresh_db_has_every_table(conn: sqlite3.Connection) -> None:
    migrate(conn)
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"accounts", "usage_log", "usage_daily", "plugins"} <= names


def test_fresh_db_has_usage_log_columns(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert {
        "skill_name",
        "status",
        "latency_ms",
        "provider_group",
        "tags",
        "error",
        "ts",
    } <= columns(conn, "usage_log")


def test_fresh_db_has_plugin_error_column(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert {"module_path", "manifest_path", "enabled", "error", "loaded_at"} <= columns(
        conn, "plugins"
    )


def test_fresh_db_has_account_tags_and_enabled(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert {"tags", "enabled"} <= columns(conn, "accounts")


def test_migrate_is_noop_on_current_db(conn: sqlite3.Connection) -> None:
    migrate(conn)
    before = conn.execute("SELECT COUNT(*) AS n FROM usage_log").fetchone()["n"]
    migrate(conn)
    migrate(conn)
    after = conn.execute("SELECT COUNT(*) AS n FROM usage_log").fetchone()["n"]
    assert before == after == 0


def test_legacy_db_gains_columns_without_losing_rows(legacy_db: str) -> None:
    conn = connect(legacy_db)
    try:
        assert {"skill_name", "status", "provider_group", "tags"} <= columns(
            conn, "usage_log"
        )
        assert {"tags", "enabled"} <= columns(conn, "accounts")
        rows = conn.execute("SELECT * FROM usage_log ORDER BY id").fetchall()
        assert len(rows) == 2
    finally:
        conn.close()


def test_legacy_usage_rows_are_backfilled(legacy_db: str) -> None:
    conn = connect(legacy_db)
    try:
        rows = conn.execute("SELECT skill_name, status, error FROM usage_log ORDER BY id").fetchall()
        assert rows[0]["skill_name"] == "echo"
        assert rows[0]["status"] == "success"
        assert rows[1]["skill_name"] == "echo"
        assert rows[1]["status"] == "error_4xx"
    finally:
        conn.close()


def test_legacy_account_gets_default_tags_and_enabled(legacy_db: str) -> None:
    conn = connect(legacy_db)
    try:
        row = conn.execute("SELECT id, tags, enabled FROM accounts").fetchone()
        assert row["id"] == 1
        assert row["tags"] == "[]"
        assert row["enabled"] == 1
    finally:
        conn.close()


def test_usage_daily_and_indexes_exist(conn: sqlite3.Connection) -> None:
    migrate(conn)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "usage_daily" in tables
    indexes = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert {
        "idx_usage_log_skill_time",
        "idx_usage_log_account_time",
    } <= indexes
