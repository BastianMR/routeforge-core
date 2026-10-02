"""Core router: dispatch a skill call against the rotation pool."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .accounts import AccountRepo
from .models import Account, AccountInfo, SkillCallResponse, UsageSummary
from .rotation import RoundRobinPool
from .skills.base import Skill, SkillError
from .skills.registry import SkillRegistry
from .usage import SUCCESS, UsageLogRepo, status_label


class RouterError(RuntimeError):
    """A dispatch could not be resolved to a usable account.

    Carries a machine-readable `code` (spec-pinned for `no_accounts_for_group`)
    plus a human-readable message for logs and legacy string matching.
    """

    code = "router_error"

    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context

    def payload(self) -> dict[str, Any]:
        return {"error": self.code, **self.context}


class NoAccountsForGroup(RouterError):
    """No account carries the tag a skill's `provider_group` requires."""

    def __init__(self, skill: str, group: str) -> None:
        super().__init__(
            "no_accounts_for_group",
            f"no accounts tagged {group!r} for skill {skill!r}",
            skill=skill,
            group=group,
        )


class AccountNotFound(RouterError):
    """A pinned `account_label` does not resolve to an enabled account."""

    def __init__(self, label: str) -> None:
        super().__init__("account_not_found", f"account not found: {label}", label=label)


class AllAccountsCooling(RouterError):
    """Every candidate account is cooling down or disabled."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            "all_accounts_cooling",
            f"all accounts for provider {provider!r} are cooling down",
            provider=provider,
        )


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
    tags: list[str] = None  # type: ignore[assignment]
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}
        if self.tags is None:
            self.tags = []


class Router:
    def __init__(
        self,
        repo: AccountRepo,
        pool: RoundRobinPool,
        registry: SkillRegistry,
        http: httpx.AsyncClient,
        conn: Any = None,
        usage: UsageLogRepo | None = None,
        events: Any = None,
    ) -> None:
        self._repo = repo
        self._pool = pool
        self._registry = registry
        self._http = http
        self._conn = conn
        self._usage = usage or (UsageLogRepo(conn) if conn is not None else None)
        self._events = events

    async def call_skill(
        self,
        name: str,
        args: dict[str, Any],
        account_label: str | None = None,
    ) -> SkillCallResponse:
        skill = self._registry.get(name)
        if skill is None:
            return SkillCallResponse(error=f"skill not found: {name}")

        try:
            account, ephemeral = await self._resolve(skill, account_label)
        except RouterError as exc:
            return SkillCallResponse(error=exc.message, error_code=exc.code)

        return await self._run(skill, account, args, ephemeral)

    async def _resolve(self, skill: Skill, account_label: str | None) -> tuple[Any, bool]:
        """Return the chosen account and whether it is the ephemeral stub.

        Raises `RouterError` when no candidate can serve the call.
        """
        if account_label is not None:
            return self._pin_account(skill, account_label), False

        candidates = self._candidates(skill)
        if not candidates:
            if not getattr(skill, "requires_account", True):
                return _EphemeralAccount(provider=skill.provider), True
            if skill.info.provider_group:
                raise NoAccountsForGroup(skill.name, skill.info.provider_group)
            raise AllAccountsCooling(skill.provider)

        account = await self._pool.pick(candidates)
        if account is None:
            if not getattr(skill, "requires_account", True):
                return _EphemeralAccount(provider=skill.provider), True
            group = skill.info.provider_group
            if group:
                raise NoAccountsForGroup(skill.name, group)
            raise AllAccountsCooling(skill.provider)
        return account, False

    def _candidates(self, skill: Skill) -> list[Account]:
        """Build the candidate set: by tag when the skill declares a group."""
        group = skill.info.provider_group
        if group:
            return self._repo.list_by_tag(group)
        return self._repo.list_by_provider(skill.provider)

    def _pin_account(self, skill: Skill, label: str) -> Account:
        accounts = self._candidates(skill)
        for account in accounts:
            if account.label == label and account.enabled:
                return account
        raise AccountNotFound(label)

    async def _run(
        self,
        skill: Skill,
        account: Any,
        args: dict[str, Any],
        ephemeral: bool,
    ) -> SkillCallResponse:
        started = time.perf_counter()
        try:
            result = await skill.execute(account, args, self._http)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if not ephemeral:
                await self._pool.mark_success(account)
                self._repo.touch(account.id)
            self._record(skill, account, SUCCESS, latency_ms, None, ephemeral)
            return SkillCallResponse(
                result=result,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )
        except SkillError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            message = str(exc)
            status = status_label(_status_from_message(message))
            if not ephemeral:
                await self._pool.mark_failure(
                    account, message, status_code=_status_from_message(message)
                )
            self._record(skill, account, status, latency_ms, message, ephemeral)
            return SkillCallResponse(
                error=message,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            latency_ms = int((time.perf_counter() - started) * 1000)
            message = f"unexpected: {exc}"
            self._record(skill, account, "error_network", latency_ms, message, ephemeral)
            return SkillCallResponse(
                error=message,
                account_id=getattr(account, "id", None),
                latency_ms=latency_ms,
            )

    def _record(
        self,
        skill: Skill,
        account: Any,
        status: str,
        latency_ms: int,
        error: str | None,
        ephemeral: bool,
    ) -> None:
        """Persist one usage row and publish `call.completed`."""
        account_id = None if ephemeral else getattr(account, "id", None)
        tags = list(getattr(account, "tags", None) or [])
        group = skill.info.provider_group
        if self._usage is not None:
            self._usage.insert(
                skill_name=skill.name,
                status=status,
                latency_ms=latency_ms,
                account_id=account_id,
                provider_group=group,
                tags=tags,
                error=error,
            )
        if self._events is not None:
            self._events.emit(
                "call.completed",
                skill=skill.name,
                account_id=account_id,
                status=status,
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
        """Aggregate usage per account and per skill.

        `by_skill` entries carry both `skill` and `skill_name` so existing
        consumers of the pre-rename key keep working.
        """
        where = "WHERE a.provider = ?" if provider is not None else ""
        params: tuple[Any, ...] = (provider,) if provider is not None else ()
        rows = self._conn.execute(
            f"""
            SELECT a.id, a.provider, a.label,
                   COUNT(u.id) AS calls,
                   SUM(CASE WHEN u.status != '{SUCCESS}' THEN 1 ELSE 0 END) AS errors
            FROM accounts a
            LEFT JOIN usage_log u ON u.account_id = a.id
            {where}
            GROUP BY a.id, a.provider, a.label
            ORDER BY a.provider, a.id
            """,
            params,
        ).fetchall()
        skill_rows = self._conn.execute(
            f"""
            SELECT skill_name,
                   COUNT(id) AS calls,
                   SUM(CASE WHEN status != '{SUCCESS}' THEN 1 ELSE 0 END) AS errors
            FROM usage_log
            GROUP BY skill_name
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
                {
                    "skill": r["skill_name"],
                    "skill_name": r["skill_name"],
                    "calls": r["calls"],
                    "errors": r["errors"] or 0,
                }
                for r in skill_rows
            ],
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
