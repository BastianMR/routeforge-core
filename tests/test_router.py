"""Tests for the Router dispatching layer."""

from __future__ import annotations

import httpx
import pytest

from routeforge.rotation import RoundRobinPool
from routeforge.router import Router
from routeforge.skills.registry import SkillRegistry


def _build_router(repo, conn) -> tuple[Router, SkillRegistry, httpx.AsyncClient]:
    registry = SkillRegistry()
    registry.discover_builtin()
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    http = httpx.AsyncClient(timeout=5.0)
    router = Router(repo, pool, registry, http, conn)
    return router, registry, http


@pytest.mark.asyncio
async def test_call_skill_dispatches_to_echo(repo, conn) -> None:
    router, _, http = _build_router(repo, conn)
    response = await router.call_skill("echo", {"x": 1, "y": [2, 3]})
    assert response.error is None
    assert response.result == {"x": 1, "y": [2, 3]}
    await http.aclose()


@pytest.mark.asyncio
async def test_call_skill_unknown_returns_error(repo, conn) -> None:
    router, _, http = _build_router(repo, conn)
    response = await router.call_skill("does-not-exist", {})
    assert response.error is not None
    assert response.error.startswith("skill not found")
    await http.aclose()


@pytest.mark.asyncio
async def test_call_skill_requires_account_when_repo_unconfigured(repo, conn) -> None:
    router, _, http = _build_router(repo, conn)
    response = await router.call_skill("firecrawl/scrape", {})
    assert response.error is not None
    assert "are cooling down" in response.error
    await http.aclose()


@pytest.mark.asyncio
async def test_usage_summary_includes_calls(repo, conn) -> None:
    router, _, http = _build_router(repo, conn)
    # echo uses an ephemeral account (no log). Add a firecrawl account and
    # call firecrawl/scrape; the upstream call will fail but the call is
    # still logged.
    repo.add(provider="firecrawl", label="f1", api_key="x")
    await router.call_skill("firecrawl/scrape", {"url": "https://example.com"})
    summary = router.usage_summary()
    assert summary.calls >= 1
    skills = {row["skill"] for row in summary.by_skill}
    assert "firecrawl/scrape" in skills
    await http.aclose()
