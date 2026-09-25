"""Core router: dispatch a skill call against the rotation pool."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .accounts import AccountRepo
from .models import Account, AccountInfo, SkillCallResponse, UsageSummary
from .rotation import RoundRobinPool
from .skills.base import Skill, SkillError
from .skills.registry import SkillRegistry


@dataclass
class _EphemeralAccount:
    """In-memory stand-in used when a skill has no registered accounts.

    Lets skills that do not need an upstream API key (e.g. `echo`) still go
    through the router pipeline. Never written to the database.
    """

    id: int = -1
    provider: str = ""
    label: str = "__ephemeral__"
    api_key: str = ""
    base_url: str | None = None
    metadata: dict[str, Any] = None  # type: ignore[assignment]
    created_at: Any = None
    last_used_at: Any = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


def _to_account_like(obj: Any) -> Account | _EphemeralAccount:
    return obj  # type: ignore[return-value]


class Router:
    def __init__(
        self,
        repo: AccountRepo,
        pool: RoundRobinPool,
        registry: SkillRegistry,
        http: httpx.AsyncClient,
        conn: sqlite3.Connection,
    ) -> None:
        self._repo = repo
        self._pool = pool
        self._registry = registry
        self._http = http
        self._conn = conn

    async def call_skill(self, name: str, args: dict[str, Any]) -> SkillCallResponse:
        skill = self._registry.get(name)
        if skill is None:
            return SkillCallResponse(error=f"skill not found: {name}")

        await self._pool.refresh(skill.provider)
        account = await self._pool.acquire(skill.provider)
        if account is None:
            # No real accounts configured for this provider. If the skill
            # declares it can run without an account, use an ephemeral stub.
            if not getattr(skill, "requires_account", True):
                ephemeral_account = _EphemeralAccount(provider=skill.provider)
                return await self._run(skill, ephemeral_account, args)
            return SkillCallResponse(
                error=f"all accounts for provider {skill.provider!r} are cooling down"
            )

        return await self._run(skill, account, args)

    async def _run(self, skill: Skill, account: Any, args: dict[str, Any]) -> SkillCallResponse:
        started = time.perf_counter()
        try:
            result = await skill.execute(account, args, self._http)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if not isinstance(account, _EphemeralAccount):
                await self._pool.mark_success(account)
                self._repo.touch(account.id)
                self._log(account.id, skill.name, 200, latency_ms, None)
            return SkillCallResponse(
                result=result,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )
        except SkillError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            message = str(exc)
            status = _status_from_message(message)
            if not isinstance(account, _EphemeralAccount):
                await self._pool.mark_failure(account, message, status_code=status)
                self._log(account.id, skill.name, status, latency_ms, message)
            return SkillCallResponse(
                error=message,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            latency_ms = int((time.perf_counter() - started) * 1000)
            message = f"unexpected: {exc}"
            if not isinstance(account, _EphemeralAccount):
                self._log(account.id, skill.name, 500, latency_ms, message)
            return SkillCallResponse(
                error=message,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )

    def list_accounts(self, provider: str | None = None) -> list[AccountInfo] | dict[str, list[AccountInfo]]:
        all_infos = self._repo.list_all()
        if provider is not None:
            return [a for a in all_infos if a.provider == provider]
        grouped: dict[str, list[AccountInfo]] = {}
        for a in all_infos:
            grouped.setdefault(a.provider, []).append(a)
        return grouped

    def usage_summary(self, provider: str | None = None) -> UsageSummary:
        params: tuple[Any, ...] = ()
        where = ""
        if provider is not None:
            where = "WHERE a.provider = ?"
            params = (provider,)
        rows = self._conn.execute(
            f"""
            SELECT a.id, a.provider, a.label,
                   COUNT(u.id) AS calls,
                   SUM(CASE WHEN u.status_code >= 400 OR u.error IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM accounts a
            LEFT JOIN usage_log u ON u.account_id = a.id
            {where}
            GROUP BY a.id, a.provider, a.label
            ORDER BY a.provider, a.id
            """,
            params,
        ).fetchall()
        skill_rows = self._conn.execute(
            """
            SELECT u.skill,
                   COUNT(u.id) AS calls,
                   SUM(CASE WHEN u.status_code >= 400 OR u.error IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM usage_log u
            GROUP BY u.skill
            ORDER BY calls DESC
            """
        ).fetchall()
        total_calls = sum(r["calls"] for r in rows)
        total_errors = sum(r["errors"] or 0 for r in rows)
        return UsageSummary(
            provider=provider,
            calls=total_calls,
            errors=total_errors,
            by_account=[
                {
                    "account_id": r["id"],
                    "provider": r["provider"],
                    "label": r["label"],
                    "calls": r["calls"],
                    "errors": r["errors"] or 0,
                }
                for r in rows
            ],
            by_skill=[
                {"skill": r["skill"], "calls": r["calls"], "errors": r["errors"] or 0}
                for r in skill_rows
            ],
        )

    def _log(
        self,
        account_id: int | None,
        skill: str,
        status: int,
        latency_ms: int,
        error: str | None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO usage_log (account_id, skill, status_code, latency_ms, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, skill, status, latency_ms, error),
            )


def _status_from_message(message: str) -> int:
    """Extract the upstream status code from a SkillError message."""
    prefix = "upstream "
    if message.startswith(prefix):
        try:
            return int(message[len(prefix):].split(":", 1)[0].strip())
        except ValueError:
            pass
    return 500


# Re-export Account-like so type checkers accept _EphemeralAccount as well.
AccountLike = Account | _EphemeralAccount
