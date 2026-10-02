"""Tests for rotation over an explicitly filtered candidate set."""

from __future__ import annotations

import asyncio

import pytest

from routeforge.events import EventBus
from routeforge.rotation import RoundRobinPool


def _tagged(repo, labels: list[str], tag: str, provider: str = "mixed") -> list:
    return [
        repo.add(provider=provider, label=label, api_key=f"k-{label}", tags=tag)
        for label in labels
    ]


@pytest.mark.asyncio
async def test_pick_rotates_over_the_candidate_set(repo) -> None:
    accounts = _tagged(repo, ["a", "b", "c"], "scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    picked = [await pool.pick(accounts) for _ in range(3)]
    assert [p.id for p in picked] == [a.id for a in accounts]


@pytest.mark.asyncio
async def test_pick_only_sees_the_candidate_set(repo) -> None:
    """Untagged accounts are invisible to a call, per Tag-Based Filtering."""
    tagged = _tagged(repo, ["a", "b", "c"], "scrape", provider="firecrawl")
    repo.add(provider="firecrawl", label="untagged", api_key="k")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    picked = [await pool.pick(tagged) for _ in range(6)]
    assert {p.id for p in picked} == {a.id for a in tagged}


@pytest.mark.asyncio
async def test_pick_rotates_across_providers_in_one_group(repo) -> None:
    firecrawl = repo.add(provider="firecrawl", label="fc", api_key="k", tags="scrape")
    tavily = repo.add(provider="tavily", label="tv", api_key="k", tags="scrape")
    exa = repo.add(provider="exa", label="ex", api_key="k", tags="scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    candidates = pool and [firecrawl, tavily, exa]
    picked = [await pool.pick(candidates) for _ in range(3)]
    assert {p.id for p in picked} == {firecrawl.id, tavily.id, exa.id}


@pytest.mark.asyncio
async def test_pick_on_empty_candidates_returns_none(repo) -> None:
    pool = RoundRobinPool(repo)
    assert await pool.pick([]) is None


@pytest.mark.asyncio
async def test_pick_skips_disabled_accounts(repo) -> None:
    _tagged(repo, ["a", "b"], "scrape")
    first, second = repo.list_by_tag("scrape")
    repo.set_enabled(first.id, False)
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    candidates = repo.list_by_tag("scrape")
    picked = [await pool.pick(candidates) for _ in range(4)]
    assert {p.id for p in picked} == {second.id}


@pytest.mark.asyncio
async def test_pick_returns_none_when_all_disabled(repo) -> None:
    _tagged(repo, ["a", "b"], "scrape")
    for account in repo.list_by_tag("scrape"):
        repo.set_enabled(account.id, False)
    pool = RoundRobinPool(repo)
    assert await pool.pick(repo.list_by_tag("scrape")) is None


@pytest.mark.asyncio
async def test_cooldown_excludes_only_the_failing_account(repo) -> None:
    a, b, c = _tagged(repo, ["a", "b", "c"], "scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    assert (await pool.pick([a, b, c])).id == a.id
    await pool.mark_failure(a, reason="upstream 429", status_code=429)

    picked = [await pool.pick([a, b, c]) for _ in range(4)]
    assert a.id not in {p.id for p in picked}
    assert {p.id for p in picked} == {b.id, c.id}


@pytest.mark.asyncio
async def test_mark_failure_ignores_plain_4xx(repo) -> None:
    _tagged(repo, ["a"], "scrape")
    (a,) = repo.list_by_tag("scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.mark_failure(a, reason="bad request", status_code=400)
    assert (await pool.pick([a])).id == a.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [402, 429, 500, 503])
async def test_mark_failure_cools_on_402_429_and_5xx(repo, status: int) -> None:
    _tagged(repo, ["a", "b"], "scrape")
    a, b = repo.list_by_tag("scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.mark_failure(a, reason=f"upstream {status}", status_code=status)
    assert (await pool.pick([a, b])).id == b.id


@pytest.mark.asyncio
async def test_concurrent_picks_hand_out_each_account_once(repo) -> None:
    accounts = _tagged(repo, ["a", "b", "c"], "scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    results = await asyncio.gather(*[pool.pick(accounts) for _ in range(3)])
    assert sorted(r.id for r in results) == sorted(a.id for a in accounts)


@pytest.mark.asyncio
async def test_cooldown_state_survives_a_candidate_refresh(repo) -> None:
    a, b = _tagged(repo, ["a", "b"], "scrape")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    await pool.mark_failure(a, reason="upstream 429", status_code=429)
    # Simulate the router re-resolving candidates from the database.
    refreshed = repo.list_by_tag("scrape")
    assert (await pool.pick(refreshed)).id == b.id


@pytest.mark.asyncio
async def test_publishes_cooldown_and_recovery_events(repo) -> None:
    a, b = _tagged(repo, ["a", "b"], "scrape")
    bus = EventBus()
    pool = RoundRobinPool(repo, default_cooldown_seconds=60, events=bus)

    await pool.mark_failure(a, reason="upstream 429", status_code=429)
    kinds = [e.type for e in bus.recent()]
    assert "account.cooldown_started" in kinds

    cooldown = next(e for e in bus.recent() if e.type == "account.cooldown_started")
    assert cooldown.data["account_id"] == a.id
    assert cooldown.data["reason"] == "429"
    assert cooldown.data["until"]

    await pool.mark_success(a)
    assert bus.recent()[-1].type == "account.recovered"


@pytest.mark.asyncio
async def test_snapshot_reports_per_account_state(repo) -> None:
    _tagged(repo, ["a", "b"], "scrape")
    a, b = repo.list_by_tag("scrape")
    repo.set_enabled(b.id, False)
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    candidates = repo.list_by_tag("scrape")
    await pool.mark_failure(candidates[0], reason="upstream 429", status_code=429)
    await pool.pick(candidates)

    snapshot = pool.snapshot()
    rows = {int(k): v for k, v in snapshot["accounts"].items()}
    assert rows[a.id]["state"] == "cooldown"
    assert rows[a.id]["consecutive_failures"] >= 1
    assert rows[a.id]["cooldown_until"] is not None
    assert rows[a.id]["last_error"] == "upstream 429"
    assert rows[a.id]["tags"] == ["scrape"]
    assert rows[b.id]["state"] == "disabled"


@pytest.mark.asyncio
async def test_snapshot_for_a_single_provider_keeps_the_legacy_shape(repo) -> None:
    _tagged(repo, ["a"], "scrape", provider="firecrawl")
    pool = RoundRobinPool(repo)
    await pool.refresh("firecrawl")
    snapshot = pool.snapshot("firecrawl")
    assert snapshot["provider"] == "firecrawl"
    assert snapshot["accounts"][0]["label"] == "a"
    assert snapshot["cooldowns"] == {}
    assert snapshot["state"][0]["state"] == "active"


@pytest.mark.asyncio
async def test_snapshot_on_an_unknown_pool_is_empty(repo) -> None:
    pool = RoundRobinPool(repo)
    assert pool.snapshot("nope") == {"provider": "nope", "accounts": [], "cooldowns": {}}
