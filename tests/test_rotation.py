"""Tests for round-robin rotation and cooldown tracking."""

from __future__ import annotations

import asyncio

import pytest

from routeforge.rotation import RoundRobinPool


@pytest.mark.asyncio
async def test_round_robin_sequential_selection(repo) -> None:
    a = repo.add(provider="firecrawl", label="a", api_key="k1")
    b = repo.add(provider="firecrawl", label="b", api_key="k2")
    c = repo.add(provider="firecrawl", label="c", api_key="k3")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("firecrawl")
    first = await pool.acquire("firecrawl")
    second = await pool.acquire("firecrawl")
    third = await pool.acquire("firecrawl")
    assert [first.id, second.id, third.id] == [a.id, b.id, c.id]


@pytest.mark.asyncio
async def test_skip_cooled_account(repo) -> None:
    a = repo.add(provider="firecrawl", label="a", api_key="k1")
    b = repo.add(provider="firecrawl", label="b", api_key="k2")
    c = repo.add(provider="firecrawl", label="c", api_key="k3")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("firecrawl")
    first = await pool.acquire("firecrawl")  # a
    assert first.id == a.id
    await pool.mark_failure(first, reason="upstream 429", status_code=429)
    second = await pool.acquire("firecrawl")  # b (a skipped)
    assert second.id == b.id
    third = await pool.acquire("firecrawl")  # c
    assert third.id == c.id
    fourth = await pool.acquire("firecrawl")  # b again (a still in cooldown)
    assert fourth.id == b.id


@pytest.mark.asyncio
async def test_mark_success_clears_cooldown_for_account(repo) -> None:
    a = repo.add(provider="firecrawl", label="a", api_key="k1")
    b = repo.add(provider="firecrawl", label="b", api_key="k2")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("firecrawl")
    first = await pool.acquire("firecrawl")
    await pool.mark_failure(first, reason="upstream 429", status_code=429)
    second = await pool.acquire("firecrawl")  # b
    assert second.id == b.id
    await pool.mark_success(first)  # explicit success on a clears its cooldown
    next_account = await pool.acquire("firecrawl")
    # Next acquire should rotate to a (cooldown cleared) then forward.
    assert next_account.id == a.id


@pytest.mark.asyncio
async def test_all_accounts_cooled_returns_none(repo) -> None:
    repo.add(provider="firecrawl", label="a", api_key="k1")
    repo.add(provider="firecrawl", label="b", api_key="k2")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("firecrawl")
    first = await pool.acquire("firecrawl")
    await pool.mark_failure(first, reason="upstream 429", status_code=429)
    second = await pool.acquire("firecrawl")
    await pool.mark_failure(second, reason="upstream 429", status_code=429)
    result = await pool.acquire("firecrawl")
    assert result is None


@pytest.mark.asyncio
async def test_no_accounts_returns_none(repo) -> None:
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("unknown")
    assert await pool.acquire("unknown") is None


@pytest.mark.asyncio
async def test_concurrent_acquires_each_account_once(repo) -> None:
    for i in range(3):
        repo.add(provider="p", label=f"a{i}", api_key=f"k{i}")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.refresh("p")
    tasks = [pool.acquire("p") for _ in range(3)]
    results = await asyncio.gather(*tasks)
    ids = [r.id for r in results]
    assert sorted(ids) == [1, 2, 3]
