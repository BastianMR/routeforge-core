"""Usage event persistence and aggregation."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

SUCCESS = "success"
_ERROR_PREFIX = "error_"

# Rows returned by `rows()` when the caller does not cap the window.
DEFAULT_ROW_LIMIT = 1000

_DURATION = re.compile(r"^(\d+)([smhd])$")


def parse_since(value: str | None) -> datetime | None:
    """Parse a relative window such as ``1h``, ``30m``, ``7d`` into a datetime.

    Returns ``None`` when the value is absent or unparseable, meaning "no
    lower bound".
    """
    if not value:
        return None
    match = _DURATION.match(value.strip().lower())
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    delta = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }[unit]
    return datetime.now(UTC).replace(tzinfo=None) - delta


def status_label(status_code: int | None) -> str:
    """Map an upstream status code to the ``usage_log.status`` vocabulary."""
    if status_code is None or status_code < 400:
        return SUCCESS
    if status_code < 500:
        return f"{_ERROR_PREFIX}4xx"
    return f"{_ERROR_PREFIX}5xx"


def is_error(status: str) -> bool:
    return status.startswith(_ERROR_PREFIX)


class UsageLogRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        skill_name: str,
        status: str,
        latency_ms: int,
        account_id: int | None = None,
        provider_group: str | None = None,
        tags: list[str] | None = None,
        error: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        """Write one usage row. Never stores request or response bodies."""
        stamp = (ts or datetime.now(UTC)).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO usage_log
                  (account_id, skill_name, ts, status, latency_ms, provider_group, tags, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    skill_name,
                    stamp,
                    status,
                    latency_ms,
                    provider_group,
                    json.dumps(tags or []),
                    error,
                ),
            )

    def rows(
        self,
        skill: str | None = None,
        since: datetime | None = None,
        limit: int = DEFAULT_ROW_LIMIT,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if skill is not None:
            clauses.append("skill_name = ?")
            params.append(skill)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since.isoformat(sep=" ", timespec="seconds"))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        raw = self._conn.execute(
            f"""
            SELECT id, ts, skill_name, account_id, status, latency_ms,
                   provider_group, tags, error
            FROM usage_log
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in raw]

    def aggregate(
        self,
        since: datetime | None = None,
        group_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Group recent usage by ``account`` or ``skill``.

        Without ``group_by`` the raw rows are returned.
        """
        if group_by is None:
            return self.rows(since=since)
        if group_by == "account":
            return self._by_account(since)
        if group_by == "skill":
            return self._by_skill(since)
        raise ValueError(f"unsupported group_by: {group_by!r}")

    def _by_account(self, since: datetime | None) -> list[dict[str, Any]]:
        clause, params = _since_clause(since)
        raw = self._conn.execute(
            f"""
            SELECT u.account_id AS account_id,
                   a.label AS account_label,
                   COUNT(u.id) AS request_count,
                   SUM(CASE WHEN u.status != '{SUCCESS}' THEN 1 ELSE 0 END) AS error_count,
                   AVG(u.latency_ms) AS avg_latency_ms
            FROM usage_log u
            LEFT JOIN accounts a ON a.id = u.account_id
            {clause}
            GROUP BY u.account_id, a.label
            ORDER BY request_count DESC, u.account_id
            """,
            params,
        ).fetchall()
        return [
            {
                "account_id": r["account_id"],
                "account_label": r["account_label"],
                "request_count": r["request_count"],
                "error_count": r["error_count"] or 0,
                "avg_latency_ms": round(r["avg_latency_ms"] or 0.0, 2),
            }
            for r in raw
        ]

    def _by_skill(self, since: datetime | None) -> list[dict[str, Any]]:
        clause, params = _since_clause(since)
        raw = self._conn.execute(
            f"""
            WITH window AS (
                SELECT skill_name, account_id, status, latency_ms
                FROM usage_log
                {clause}
            ),
            totals AS (
                SELECT skill_name,
                       COUNT(*) AS request_count,
                       SUM(CASE WHEN status != '{SUCCESS}' THEN 1 ELSE 0 END) AS error_count,
                       AVG(latency_ms) AS avg_latency_ms
                FROM window
                GROUP BY skill_name
            ),
            top AS (
                SELECT skill_name, account_id, ROW_NUMBER() OVER (
                    PARTITION BY skill_name ORDER BY COUNT(*) DESC, account_id
                ) AS rank
                FROM window
                WHERE account_id IS NOT NULL
                GROUP BY skill_name, account_id
            )
            SELECT t.skill_name, t.request_count, t.error_count, t.avg_latency_ms,
                   (SELECT p.account_id FROM top p
                     WHERE p.skill_name = t.skill_name AND p.rank = 1) AS top_account_id
            FROM totals t
            ORDER BY t.request_count DESC, t.skill_name
            """,
            params,
        ).fetchall()
        return [
            {
                "skill_name": r["skill_name"],
                "request_count": r["request_count"],
                "error_count": r["error_count"] or 0,
                "avg_latency_ms": round(r["avg_latency_ms"] or 0.0, 2),
                "top_account_id": r["top_account_id"],
            }
            for r in raw
        ]

    def rollup(self, days: int = 1) -> int:
        """Upsert the last `days` of `usage_log` into `usage_daily`.

        Returns the number of rollup rows written.
        """
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        raw = self._conn.execute(
            """
            SELECT date(ts) AS day, skill_name, account_id, status,
                   COUNT(id) AS request_count,
                   SUM(CASE WHEN status != ? THEN 1 ELSE 0 END) AS error_count,
                   AVG(latency_ms) AS avg_latency_ms
            FROM usage_log
            WHERE ts >= ? AND account_id IS NOT NULL
            GROUP BY day, skill_name, account_id, status
            """,
            (SUCCESS, since.isoformat(sep=" ", timespec="seconds")),
        ).fetchall()
        latencies = self._latency_percentile(since)
        written = 0
        with self._conn:
            for row in raw:
                key = (row["day"], row["skill_name"], row["account_id"], row["status"])
                p95 = latencies.get(key, 0.0)
                self._conn.execute(
                    """
                    INSERT INTO usage_daily
                      (day, skill_name, account_id, status, request_count,
                       error_count, avg_latency_ms, p95_latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(day, skill_name, account_id, status) DO UPDATE SET
                      request_count = excluded.request_count,
                      error_count = excluded.error_count,
                      avg_latency_ms = excluded.avg_latency_ms,
                      p95_latency_ms = excluded.p95_latency_ms
                    """,
                    (
                        row["day"],
                        row["skill_name"],
                        row["account_id"],
                        row["status"],
                        row["request_count"],
                        row["error_count"] or 0,
                        round(row["avg_latency_ms"] or 0.0, 2),
                        p95,
                    ),
                )
                written += 1
        return written

    def _latency_percentile(self, since: datetime) -> dict[tuple[Any, ...], float]:
        """Per-group p95 latency, computed in Python to stay SQLite-version safe."""
        raw = self._conn.execute(
            """
            SELECT date(ts) AS day, skill_name, account_id, status, latency_ms
            FROM usage_log
            WHERE ts >= ? AND account_id IS NOT NULL AND latency_ms IS NOT NULL
            ORDER BY skill_name, account_id, latency_ms
            """,
            (since.isoformat(sep=" ", timespec="seconds"),),
        ).fetchall()
        groups: dict[tuple[Any, ...], list[int]] = {}
        for row in raw:
            key = (row["day"], row["skill_name"], row["account_id"], row["status"])
            groups.setdefault(key, []).append(row["latency_ms"])
        result: dict[tuple[Any, ...], float] = {}
        for key, values in groups.items():
            index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
            result[key] = float(values[index])
        return result

    def prune(self, older_than: datetime) -> int:
        """Delete usage rows older than `older_than`. Returns rows removed."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM usage_log WHERE ts < ?",
                (older_than.isoformat(sep=" ", timespec="seconds"),),
            )
        return cursor.rowcount or 0

    def counts(self, since: datetime | None = None) -> tuple[int, int]:
        """Return ``(requests, errors)`` for the window, used by ``usage.tick``."""
        clause, params = _since_clause(since)
        row = self._conn.execute(
            f"""
            SELECT COUNT(id) AS requests,
                   SUM(CASE WHEN status != '{SUCCESS}' THEN 1 ELSE 0 END) AS errors
            FROM usage_log
            {clause}
            """,
            params,
        ).fetchone()
        return (row["requests"] or 0, row["errors"] or 0)


def _since_clause(since: datetime | None) -> tuple[str, list[Any]]:
    if since is None:
        return "", []
    return "WHERE ts >= ?", [since.isoformat(sep=" ", timespec="seconds")]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "skill_name": row["skill_name"],
        "account_id": row["account_id"],
        "status": row["status"],
        "latency_ms": row["latency_ms"],
        "provider_group": row["provider_group"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "error": row["error"],
    }
