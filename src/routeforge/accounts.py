"""CRUD for accounts in the encrypted SQLite store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .models import Account, AccountInfo
from .secrets import Secrets


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    """Accept a comma-separated string or a list; return de-duplicated order-preserving tags."""
    if tags is None:
        return []
    if isinstance(tags, str):
        parts = tags.split(",")
    else:
        parts = list(tags)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        tag = str(part).strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


class AccountRepo:
    def __init__(self, conn: sqlite3.Connection, secrets: Secrets) -> None:
        self._conn = conn
        self._secrets = secrets

    def add(
        self,
        provider: str,
        label: str,
        api_key: str,
        base_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | str | None = None,
        enabled: bool = True,
    ) -> Account:
        encrypted = self._secrets.encrypt(api_key)
        meta_json = json.dumps(metadata or {})
        tags_json = json.dumps(normalize_tags(tags))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO accounts
                  (provider, label, api_key_encrypted, base_url, metadata_json, tags, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, label) DO UPDATE SET
                  api_key_encrypted = excluded.api_key_encrypted,
                  base_url = excluded.base_url,
                  metadata_json = excluded.metadata_json,
                  tags = excluded.tags,
                  enabled = excluded.enabled
                """,
                (provider, label, encrypted, base_url, meta_json, tags_json, int(enabled)),
            )
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE provider = ? AND label = ?", (provider, label)
        ).fetchone()
        return self._row_to_account(row)

    def list_by_provider(self, provider: str) -> list[Account]:
        rows = self._conn.execute(
            "SELECT * FROM accounts WHERE provider = ? ORDER BY id", (provider,)
        ).fetchall()
        return [self._row_to_account(r) for r in rows]

    def list_all_accounts(self) -> list[Account]:
        """Every account with its decrypted key. Callers must not log the result."""
        rows = self._conn.execute("SELECT * FROM accounts ORDER BY provider, id").fetchall()
        return [self._row_to_account(r) for r in rows]

    def get_by_id(self, account_id: int) -> Account | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._row_to_account(row) if row is not None else None

    def get_by_label(self, label: str) -> Account | None:
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE label = ? ORDER BY id LIMIT 1", (label,)
        ).fetchone()
        return self._row_to_account(row) if row is not None else None

    def list_by_tag(self, tag: str) -> list[Account]:
        """Accounts whose tags contain `tag`.

        Uses a LIKE against the JSON array, which is exact enough here because
        normalize_tags forbids whitespace inside a tag.
        """
        rows = self._conn.execute(
            """
            SELECT * FROM accounts
            WHERE tags LIKE ?
            ORDER BY id
            """,
            (f'%"{tag}"%',),
        ).fetchall()
        return [self._row_to_account(r) for r in rows]

    def list_tags(self) -> list[str]:
        """Every distinct tag across all accounts, sorted."""
        rows = self._conn.execute("SELECT tags FROM accounts").fetchall()
        seen: set[str] = set()
        for row in rows:
            seen.update(_load_tags(row["tags"]))
        return sorted(seen)

    def update_tags(self, account_id: int, tags: list[str] | str | None) -> list[str]:
        """Replace an account's tags. Returns the stored list."""
        if self.get_by_id(account_id) is None:
            raise KeyError(f"account not found: {account_id}")
        normalized = normalize_tags(tags)
        with self._conn:
            self._conn.execute(
                "UPDATE accounts SET tags = ? WHERE id = ?",
                (json.dumps(normalized), account_id),
            )
        return normalized

    def add_tags(self, account_id: int, tags: list[str] | str | None) -> list[str]:
        account = self.get_by_id(account_id)
        if account is None:
            raise KeyError(f"account not found: {account_id}")
        merged = normalize_tags([*account.tags, *normalize_tags(tags)])
        return self.update_tags(account_id, merged)

    def remove_tags(self, account_id: int, tags: list[str] | str | None) -> list[str]:
        account = self.get_by_id(account_id)
        if account is None:
            raise KeyError(f"account not found: {account_id}")
        drop = set(normalize_tags(tags))
        remaining = [t for t in account.tags if t not in drop]
        return self.update_tags(account_id, remaining)

    def set_enabled(self, account_id: int, enabled: bool) -> bool:
        """Set the enabled flag. Returns the stored value."""
        with self._conn:
            self._conn.execute(
                "UPDATE accounts SET enabled = ? WHERE id = ?",
                (int(enabled), account_id),
            )
        row = self._conn.execute(
            "SELECT enabled FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"account not found: {account_id}")
        return bool(row["enabled"])

    def toggle_enabled(self, account_id: int) -> bool:
        """Invert the enabled flag. Returns the new value."""
        account = self.get_by_id(account_id)
        if account is None:
            raise KeyError(f"account not found: {account_id}")
        return self.set_enabled(account_id, not account.enabled)

    def list_all(self) -> list[AccountInfo]:
        rows = self._conn.execute(
            "SELECT id, provider, label, base_url, metadata_json, tags, enabled, last_used_at "
            "FROM accounts ORDER BY provider, id"
        ).fetchall()
        result: list[AccountInfo] = []
        for r in rows:
            meta: dict[str, Any] = {}
            if r["metadata_json"]:
                meta = json.loads(r["metadata_json"])
            result.append(
                AccountInfo(
                    id=r["id"],
                    provider=r["provider"],
                    label=r["label"],
                    base_url=r["base_url"],
                    metadata=meta,
                    tags=_load_tags(r["tags"]),
                    enabled=bool(r["enabled"]),
                    last_used_at=_parse_dt(r["last_used_at"]),
                )
            )
        return result

    def touch(self, account_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE accounts SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (account_id,),
            )

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        meta: dict[str, Any] = {}
        if row["metadata_json"]:
            meta = json.loads(row["metadata_json"])
        return Account(
            id=row["id"],
            provider=row["provider"],
            label=row["label"],
            api_key=self._secrets.decrypt(row["api_key_encrypted"]),
            base_url=row["base_url"],
            metadata=meta,
            tags=_load_tags(row["tags"]),
            enabled=bool(row["enabled"]),
            created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
            last_used_at=_parse_dt(row["last_used_at"]),
        )


def _load_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(t) for t in loaded] if isinstance(loaded, list) else []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace(" ", "T"))
