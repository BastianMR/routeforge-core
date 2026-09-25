"""Tests for builtin skills."""

from __future__ import annotations

import httpx
import pytest
import respx

from routeforge.accounts import AccountRepo
from routeforge.models import Account
from routeforge.skills.builtin.echo import EchoSkill
from routeforge.skills.builtin.firecrawl import FirecrawlScrapeSkill


def _dummy_account(repo: AccountRepo, label: str = "x") -> Account:
    return repo.add(
        provider="firecrawl",
        label=label,
        api_key="fc-test",
        base_url="https://api.firecrawl.dev",
    )


@pytest.mark.asyncio
async def test_echo_skill_returns_args(repo) -> None:
    skill = EchoSkill()
    async with httpx.AsyncClient() as http:
        result = await skill.execute(_dummy_account(repo), {"k": "v"}, http)
    assert result == {"k": "v"}


@pytest.mark.asyncio
async def test_firecrawl_skill_builds_correct_request(repo) -> None:
    account = _dummy_account(repo)
    with respx.mock(base_url="https://api.firecrawl.dev") as mock:
        route = mock.post("/v1/scrape").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"markdown": "# hi", "metadata": {"title": "t"}}},
            )
        )
        async with httpx.AsyncClient() as http:
            skill = FirecrawlScrapeSkill()
            result = await skill.execute(
                account,
                {"url": "https://example.com", "formats": ["markdown"]},
                http,
            )
        assert result == {"markdown": "# hi", "metadata": {"title": "t"}}
        assert route.called
        # Inspect what we sent
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer fc-test"
        import json
        body = json.loads(request.content)
        assert body["url"] == "https://example.com"
        assert body["formats"] == ["markdown"]


@pytest.mark.asyncio
async def test_firecrawl_skill_surfaces_upstream_error(repo) -> None:
    account = _dummy_account(repo)
    with respx.mock(base_url="https://api.firecrawl.dev") as mock:
        mock.post("/v1/scrape").mock(return_value=httpx.Response(429, text="rate limited"))
        from routeforge.skills.base import SkillError
        async with httpx.AsyncClient() as http:
            skill = FirecrawlScrapeSkill()
            with pytest.raises(SkillError, match="upstream 429"):
                await skill.execute(account, {"url": "https://example.com"}, http)


@pytest.mark.asyncio
async def test_firecrawl_skill_requires_url(repo) -> None:
    from routeforge.skills.base import SkillError
    account = _dummy_account(repo)
    async with httpx.AsyncClient() as http:
        skill = FirecrawlScrapeSkill()
        with pytest.raises(SkillError, match="'url' is required"):
            await skill.execute(account, {}, http)
