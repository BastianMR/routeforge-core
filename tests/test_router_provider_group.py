"""Tests for provider-group dispatch in the router."""

from __future__ import annotations

import httpx
import pytest

from routeforge.rotation import RoundRobinPool
from routeforge.router import Router
from routeforge.skills.base import Skill
from routeforge.skills.registry import SkillRegistry


class GroupedEcho(Skill):
    """Records which account it was handed, so tests can assert the rotation."""

    name = "grouped-echo"
    provider = "ignored-provider"
    description = "Echoes args plus the tags of the account it received."
    provider_group = "scrape"

    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        self.seen.append(list(account.tags))
        return {"args": args, "tags": list(account.tags)}


class ProviderEcho(Skill):
    name = "provider-echo"
    provider = "widget"
    description = "Echoes args; resolved by provider, not tag."

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        return {"args": args, "label": account.label}


def _router(repo, conn, registry: SkillRegistry) -> tuple[Router, httpx.AsyncClient]:
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    http = httpx.AsyncClient(timeout=5.0)
    return Router(repo, pool, registry, http, conn), http


@pytest.fixture
def grouped_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.discover_builtin()
    registry.register(GroupedEcho(), "plugin")
    registry.register(ProviderEcho(), "builtin")
    return registry


@pytest.mark.asyncio
async def test_grouped_skill_only_sees_tagged_accounts(
    repo, conn, grouped_registry
) -> None:
    repo.add(provider="firecrawl", label="fc", api_key="k", tags="scrape")
    repo.add(provider="tavily", label="tv", api_key="k", tags="scrape")
    repo.add(provider="exa", label="ex", api_key="k", tags="search")

    router, http = _router(repo, conn, grouped_registry)
    response = await router.call_skill("grouped-echo", {"x": 1})
    assert response.error is None
    assert response.result["tags"] == ["scrape"]
    await http.aclose()


@pytest.mark.asyncio
async def test_grouped_dispatch_rotates_across_providers(
    repo, conn, grouped_registry
) -> None:
    repo.add(provider="firecrawl", label="fc", api_key="k", tags="scrape")
    repo.add(provider="tavily", label="tv", api_key="k", tags="scrape")

    router, http = _router(repo, conn, grouped_registry)
    skill = grouped_registry.get("grouped-echo")
    for _ in range(4):
        await router.call_skill("grouped-echo", {})
    assert sorted(skill.seen) == [["scrape"], ["scrape"], ["scrape"], ["scrape"]]
    await http.aclose()


@pytest.mark.asyncio
async def test_no_account_for_group_raises_the_spec_error(
    repo, conn, grouped_registry
) -> None:
    repo.add(provider="firecrawl", label="fc", api_key="k", tags="search")

    router, http = _router(repo, conn, grouped_registry)
    response = await router.call_skill("grouped-echo", {})
    assert response.error_code == "no_accounts_for_group"
    assert "scrape" in response.error
    await http.aclose()


@pytest.mark.asyncio
async def test_skill_without_group_still_resolves_by_provider(
    repo, conn, grouped_registry
) -> None:
    repo.add(provider="widget", label="w1", api_key="k", tags="anything")
    repo.add(provider="other", label="o1", api_key="k", tags="scrape")

    router, http = _router(repo, conn, grouped_registry)
    response = await router.call_skill("provider-echo", {"y": 2})
    assert response.error is None
    assert response.result["label"] == "w1"
    await http.aclose()


@pytest.mark.asyncio
async def test_group_dispatch_skips_disabled_accounts(repo, conn, grouped_registry) -> None:
    disabled = repo.add(provider="firecrawl", label="fc", api_key="k", tags="scrape")
    repo.add(provider="tavily", label="tv", api_key="k", tags="scrape")
    repo.set_enabled(disabled.id, False)

    router, http = _router(repo, conn, grouped_registry)
    for _ in range(3):
        response = await router.call_skill("grouped-echo", {})
        assert response.result["tags"] == ["scrape"]
    assert disabled.id != response.account_id
    await http.aclose()


@pytest.mark.asyncio
async def test_group_dispatch_excludes_untagged_accounts(
    repo, conn, grouped_registry
) -> None:
    repo.add(provider="firecrawl", label="fc", api_key="k")  # no tags
    repo.add(provider="tavily", label="tv", api_key="k", tags="scrape")

    router, http = _router(repo, conn, grouped_registry)
    response = await router.call_skill("grouped-echo", {})
    assert response.result is not None
    await http.aclose()
    assert router._repo.list_by_tag("scrape")[0].label == "tv"


@pytest.mark.asyncio
async def test_all_group_accounts_cooling_reports_group_error(
    repo, conn, grouped_registry
) -> None:
    only = repo.add(provider="firecrawl", label="fc", api_key="k", tags="scrape")
    router, http = _router(repo, conn, grouped_registry)
    await router._pool.mark_failure(only, reason="upstream 429", status_code=429)

    response = await router.call_skill("grouped-echo", {})
    assert response.error_code == "no_accounts_for_group"
    await http.aclose()


@pytest.mark.asyncio
async def test_ephemeral_account_still_bypasses_the_pool(repo, conn) -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    router, http = _router(repo, conn, registry)

    response = await router.call_skill("echo", {"k": "v"})
    assert response.result == {"k": "v"}
    assert response.account_id == -1
    await http.aclose()


@pytest.mark.asyncio
async def test_pinned_account_label_bypasses_rotation(repo, conn) -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    repo.add(provider="firecrawl", label="fc1", api_key="k1", base_url="https://api.firecrawl.dev")
    repo.add(provider="firecrawl", label="fc2", api_key="k2", base_url="https://api.firecrawl.dev")
    router, http = _router(repo, conn, registry)

    pinned = repo.get_by_label("fc1")
    response = await router.call_skill(
        "firecrawl/scrape", {"url": "https://example.com"}, account_label="fc1"
    )
    assert response.error is not None  # no network in tests
    assert response.account_id == pinned.id
    await http.aclose()


@pytest.mark.asyncio
async def test_unknown_pinned_label_reports_account_not_found(repo, conn) -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    repo.add(provider="firecrawl", label="fc1", api_key="k1")
    router, http = _router(repo, conn, registry)

    response = await router.call_skill("firecrawl/scrape", {}, account_label="ghost")
    assert response.error_code == "account_not_found"
    await http.aclose()


@pytest.mark.asyncio
async def test_disabled_pinned_label_reports_account_not_found(repo, conn) -> None:
    registry = SkillRegistry()
    registry.discover_builtin()
    account = repo.add(provider="firecrawl", label="fc1", api_key="k1")
    repo.set_enabled(account.id, False)
    router, http = _router(repo, conn, registry)

    response = await router.call_skill("firecrawl/scrape", {}, account_label="fc1")
    assert response.error_code == "account_not_found"
    await http.aclose()
