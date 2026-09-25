"""CRUD for accounts in the encrypted SQLite store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .models import Account, AccountInfo
from .secrets import Secrets


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
    ) -> Account:
        encrypted = self._secrets.encrypt(api_key)
        meta_json = json.dumps(metadata or {})
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO accounts (provider, label, api_key_encrypted, base_url, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, label) DO UPDATE SET
                  api_key_encrypted = excluded.api_key_encrypted,
                  base_url = excluded.base_url,
                  metadata_json = excluded.metadata_json
                """,
                (provider, label, encrypted, base_url, meta_json),
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

    def list_all(self) -> list[AccountInfo]:
        rows = self._conn.execute(
            "SELECT id, provider, label, base_url, metadata_json, last_used_at "
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
            created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
            last_used_at=_parse_dt(row["last_used_at"]),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace(" ", "T"))
