"""Round-robin account pool with cooldown tracking."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .accounts import AccountRepo
from .models import Account


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
    locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    pool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RoundRobinPool:
    """Holds one Pool per provider. Async-safe."""

    def __init__(self, repo: AccountRepo, default_cooldown_seconds: int = 60) -> None:
        self._repo = repo
        self._default_cooldown = default_cooldown_seconds
        self._pools: dict[str, Pool] = {}
        self._global_lock = asyncio.Lock()

    async def refresh(self, provider: str) -> Pool:
        async with self._global_lock:
            accounts = self._repo.list_by_provider(provider)
            existing = self._pools.get(provider)
            kept_cooldowns: dict[int, CooldownState] = {}
            kept_locks: dict[int, asyncio.Lock] = {}
            if existing is not None:
                for acc in existing.accounts:
                    if acc.id in existing.cooldowns:
                        kept_cooldowns[acc.id] = existing.cooldowns[acc.id]
                    kept_locks[acc.id] = existing.locks.get(acc.id, asyncio.Lock())
            for acc in accounts:
                kept_locks.setdefault(acc.id, asyncio.Lock())
            new_pool = Pool(
                provider=provider,
                accounts=accounts,
                cursor=existing.cursor if existing else 0,
                cooldowns=kept_cooldowns,
                locks=kept_locks,
            )
            self._pools[provider] = new_pool
            return new_pool

    async def get_pool(self, provider: str) -> Pool:
        pool = self._pools.get(provider)
        if pool is None:
            return await self.refresh(provider)
        return pool

    async def acquire(self, provider: str) -> Account | None:
        pool = await self.get_pool(provider)
        if not pool.accounts:
            return None
        async with pool.pool_lock:
            now = time.monotonic()
            n = len(pool.accounts)
            for offset in range(n):
                idx = (pool.cursor + offset) % n
                account = pool.accounts[idx]
                state = pool.cooldowns.get(account.id)
                if state and state.until_monotonic > now:
                    continue
                # advance cursor past this account so the next call starts after it
                pool.cursor = (idx + 1) % n
                if state:
                    pool.cooldowns.pop(account.id, None)
                return account
        return None

    async def mark_failure(self, account: Account, reason: str, status_code: int | None = None) -> None:
        pool = await self.get_pool(account.provider)
        cooldown_seconds = self._cooldown_for(account)
        if status_code is not None and status_code < 500 and status_code not in (402, 429):
            # not a cooldown-triggering failure
            return
        async with pool.pool_lock:
            pool.cooldowns[account.id] = CooldownState(
                until_monotonic=time.monotonic() + cooldown_seconds,
                reason=reason,
            )

    async def mark_success(self, account: Account) -> None:
        pool = await self.get_pool(account.provider)
        async with pool.pool_lock:
            pool.cooldowns.pop(account.id, None)

    async def lock_for(self, account: Account) -> asyncio.Lock:
        pool = await self.get_pool(account.provider)
        async with pool.pool_lock:
            return pool.locks.setdefault(account.id, asyncio.Lock())

    def _cooldown_for(self, account: Account) -> int:
        meta = account.metadata or {}
        value = meta.get("cooldown_seconds")
        if isinstance(value, int) and value > 0:
            return value
        return self._default_cooldown

    def snapshot(self, provider: str) -> dict[str, Any]:
        pool = self._pools.get(provider)
        if pool is None:
            return {"provider": provider, "accounts": [], "cooldowns": {}}
        now = time.monotonic()
        cooldowns: dict[str, dict[str, Any]] = {}
        for acc_id, state in pool.cooldowns.items():
            remaining = max(0.0, state.until_monotonic - now)
            cooldowns[str(acc_id)] = {"reason": state.reason, "remaining_seconds": round(remaining, 2)}
        return {
            "provider": provider,
            "accounts": [
                {"id": a.id, "label": a.label} for a in pool.accounts
            ],
            "cooldowns": cooldowns,
        }
