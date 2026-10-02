"""Round-robin account pool with cooldown tracking."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .accounts import AccountRepo
from .events import EventBus
from .events.bus import COOLDOWN_STARTED, DISABLED, RECOVERED
from .models import Account

# Status codes that put an account into cooldown. Other 4xx are treated as
# caller errors and must not penalize the account.
COOLDOWN_STATUS = frozenset({402, 429})


@dataclass
class CooldownState:
    until_monotonic: float = 0.0
    reason: str = ""


@dataclass
class Pool:
    provider: str
    accounts: list[Account]
    cursor: int = 0
    cooldowns: dict[int, CooldownState] = field(default_factory=dict)
    failures: dict[int, int] = field(default_factory=dict)
    locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    pool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RoundRobinPool:
    """Holds one Pool per provider. Async-safe.

    `pick()` is the selection entry point: the caller passes the already
    filtered candidate set, so the pool never needs to know about tags.
    """

    def __init__(
        self,
        repo: AccountRepo,
        default_cooldown_seconds: int = 60,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._default_cooldown = default_cooldown_seconds
        self._events = events
        self._pools: dict[str, Pool] = {}
        self._global_lock = asyncio.Lock()

    async def refresh(self, provider: str) -> Pool:
        async with self._global_lock:
            accounts = self._repo.list_by_provider(provider)
            return self._rebuild(provider, accounts)

    def _rebuild(self, provider: str, accounts: list[Account]) -> Pool:
        existing = self._pools.get(provider)
        kept_cooldowns: dict[int, CooldownState] = {}
        kept_failures: dict[int, int] = {}
        kept_locks: dict[int, asyncio.Lock] = {}
        if existing is not None:
            for acc in existing.accounts:
                if acc.id in existing.cooldowns:
                    kept_cooldowns[acc.id] = existing.cooldowns[acc.id]
                kept_failures[acc.id] = existing.failures.get(acc.id, 0)
            kept_locks = dict(existing.locks)
        for acc in accounts:
            kept_locks.setdefault(acc.id, asyncio.Lock())
        new_pool = Pool(
            provider=provider,
            accounts=accounts,
            cursor=existing.cursor if existing else 0,
            cooldowns=kept_cooldowns,
            failures=kept_failures,
            locks=kept_locks,
        )
        self._pools[provider] = new_pool
        return new_pool

    async def get_pool(self, provider: str) -> Pool:
        pool = self._pools.get(provider)
        if pool is None:
            return await self.refresh(provider)
        return pool

    async def pick(self, candidates: list[Account]) -> Account | None:
        """Round-robin over `candidates`, skipping cooled and disabled accounts.

        Returns None when every candidate is unavailable.
        """
        if not candidates:
            return None
        provider = candidates[0].provider
        await self._sync(provider, candidates)
        pool = self._pools[provider]
        usable = [a for a in candidates if a.enabled]
        if not usable:
            return None
        async with pool.pool_lock:
            now = time.monotonic()
            n = len(usable)
            for offset in range(n):
                idx = (pool.cursor + offset) % n
                account = usable[idx]
                state = pool.cooldowns.get(account.id)
                if state and state.until_monotonic > now:
                    continue
                pool.cursor = (idx + 1) % n
                if state is not None:
                    pool.cooldowns.pop(account.id, None)
                    self._emit(RECOVERED, account_id=account.id)
                return account
        return None

    async def acquire(self, provider: str) -> Account | None:
        """Select from every account of `provider`. Kept for callers that have
        not yet moved to explicit candidate sets."""
        candidates = self._repo.list_by_provider(provider)
        return await self.pick(candidates)

    async def _sync(self, provider: str, candidates: list[Account]) -> None:
        """Keep the stored pool aligned with the candidate set, preserving
        cursor, cooldowns, and per-account locks across refreshes."""
        pool = self._pools.get(provider)
        if pool is not None and [a.id for a in pool.accounts] == [a.id for a in candidates]:
            # Only metadata such as `enabled` or `tags` may have moved.
            pool.accounts = list(candidates)
            return
        await self._rebuild_async(provider, candidates)

    async def _rebuild_async(self, provider: str, candidates: list[Account]) -> None:
        async with self._global_lock:
            self._rebuild(provider, candidates)

    async def mark_failure(
        self, account: Account, reason: str, status_code: int | None = None
    ) -> None:
        """Cool an account down on 429, 402, or 5xx. Other 4xx are ignored."""
        pool = await self.get_pool(account.provider)
        if status_code is not None and status_code < 500 and status_code not in COOLDOWN_STATUS:
            return
        cooldown_seconds = self._cooldown_for(account)
        until_monotonic = 0.0
        async with pool.pool_lock:
            until_monotonic = time.monotonic() + cooldown_seconds
            pool.cooldowns[account.id] = CooldownState(
                until_monotonic=until_monotonic,
                reason=reason,
            )
            pool.failures[account.id] = pool.failures.get(account.id, 0) + 1
        self._emit(
            COOLDOWN_STARTED,
            account_id=account.id,
            until=(_utcnow() + timedelta(seconds=cooldown_seconds)).isoformat(),
            reason=str(status_code) if status_code is not None else reason,
        )

    async def mark_success(self, account: Account) -> None:
        pool = await self.get_pool(account.provider)
        was_cooling = False
        async with pool.pool_lock:
            was_cooling = pool.cooldowns.pop(account.id, None) is not None
            pool.failures[account.id] = 0
        if was_cooling:
            self._emit(RECOVERED, account_id=account.id)

    async def lock_for(self, account: Account) -> asyncio.Lock:
        pool = await self.get_pool(account.provider)
        async with pool.pool_lock:
            return pool.locks.setdefault(account.id, asyncio.Lock())

    async def announce_disabled(self, account_id: int, provider: str) -> None:
        """Publish `account.disabled`; kept next to the pool because it is the
        pool's job to keep callers from picking a disabled account."""
        self._emit(DISABLED, account_id=account_id)

    def _cooldown_for(self, account: Account) -> int:
        meta = account.metadata or {}
        value = meta.get("cooldown_seconds")
        if isinstance(value, int) and value > 0:
            return value
        return self._default_cooldown

    def snapshot(self, provider: str | None = None) -> dict[str, Any]:
        """Per-account pool state for the TUI Accounts tab.

        Pass a provider for the legacy `{provider, accounts, cooldowns}` shape,
        or nothing for the flat `{account_id: {...}}` map the TUI consumes.
        """
        if provider is not None:
            return self._provider_snapshot(provider)
        accounts: dict[str, Any] = {}
        for pool in self._pools.values():
            for account in pool.accounts:
                accounts[str(account.id)] = self._account_state(pool, account)
        return {"accounts": accounts}

    def _provider_snapshot(self, provider: str) -> dict[str, Any]:
        pool = self._pools.get(provider)
        if pool is None:
            return {"provider": provider, "accounts": [], "cooldowns": {}}
        rows = [self._account_state(pool, a) for a in pool.accounts]
        return {
            "provider": provider,
            "accounts": [{"id": a.id, "label": a.label} for a in pool.accounts],
            "cooldowns": {
                str(row["account_id"]): {
                    "reason": pool.cooldowns[a.id].reason,
                    "remaining_seconds": row["cooldown_remaining_seconds"],
                }
                for a, row in zip(pool.accounts, rows, strict=True)
                if a.id in pool.cooldowns
            },
            "state": rows,
        }

    def _account_state(self, pool: Pool, account: Account) -> dict[str, Any]:
        now = time.monotonic()
        cooldown = pool.cooldowns.get(account.id)
        remaining = max(0.0, cooldown.until_monotonic - now) if cooldown else 0.0
        if not account.enabled:
            state = "disabled"
        elif remaining > 0:
            state = "cooldown"
        else:
            state = "active"
        return {
            "account_id": account.id,
            "label": account.label,
            "provider": account.provider,
            "tags": list(account.tags),
            "state": state,
            "cooldown_until": (
                (_utcnow() + timedelta(seconds=remaining)).isoformat() if remaining > 0 else None
            ),
            "cooldown_remaining_seconds": round(remaining, 2),
            "consecutive_failures": pool.failures.get(account.id, 0),
            "last_used_at": account.last_used_at.isoformat() if account.last_used_at else None,
            "last_error": cooldown.reason if cooldown else None,
        }

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._events is not None:
            self._events.emit(event_type, **data)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
