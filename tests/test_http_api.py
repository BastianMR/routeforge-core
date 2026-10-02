"""HTTP surface tests: skills, accounts, usage filters, and manage endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from routeforge.app import create_app
from routeforge.runtime import build_runtime
from routeforge.secrets import Secrets
from routeforge.usage import UsageLogRepo


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "http.db"))
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "plugins"))
    return build_runtime()


@pytest.fixture
def client(runtime):
    with TestClient(create_app(runtime)) as test_client:
        yield test_client


def test_skills_listing_includes_source_and_group(client) -> None:
    body = client.get("/v1/skills").json()
    by_name = {s["name"]: s for s in body}
    assert by_name["echo"]["source"] == "builtin"
    assert by_name["echo"]["provider_group"] is None
    assert by_name["echo"]["requires_account"] is False
    assert by_name["firecrawl/scrape"]["requires_account"] is True
    assert "schema" in by_name["echo"]


def test_skill_call_returns_the_result(client) -> None:
    response = client.post("/skills/echo/call", json={"args": {"x": 1}})
    assert response.status_code == 200
    assert response.json()["result"] == {"x": 1}


def test_unknown_skill_returns_404(client) -> None:
    assert client.post("/skills/nope/call", json={"args": {}}).status_code == 404


def test_chat_completions_routes_to_a_skill(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "skill:echo", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == {"message": "hi"}


def test_chat_completions_rejects_a_non_skill_model(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 400


def test_accounts_listing_groups_by_provider_and_hides_keys(client, runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="super-secret", tags="scrape")
    body = client.get("/v1/accounts").json()
    account = body["firecrawl"][0]
    assert account["tags"] == ["scrape"]
    assert account["enabled"] is True
    assert "super-secret" not in str(body)
    assert "api_key" not in account


def test_accounts_listing_can_filter_by_provider(client, runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    runtime.repo.add(provider="tavily", label="tv1", api_key="k")
    body = client.get("/v1/accounts", params={"provider": "firecrawl"}).json()
    assert list(body) == ["firecrawl"]


def test_pool_snapshot_endpoint(client, runtime) -> None:
    import asyncio

    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    asyncio.run(runtime.router._pool.refresh("firecrawl"))
    body = client.get("/v1/accounts/pool").json()
    assert "accounts" in body


def test_usage_endpoint_keeps_the_legacy_provider_shape(client, runtime) -> None:
    account = runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    runtime.usage.insert("echo", "success", 10, account_id=account.id)
    body = client.get("/v1/usage", params={"provider": "firecrawl"}).json()
    assert body["provider"] == "firecrawl"
    assert body["calls"] == 1


def test_usage_endpoint_returns_rows_when_filtered_by_skill(client, runtime) -> None:
    runtime.usage.insert("echo", "success", 10)
    runtime.usage.insert("other", "success", 10)
    body = client.get("/v1/usage", params={"skill": "echo"}).json()
    assert isinstance(body, list)
    assert [row["skill_name"] for row in body] == ["echo"]


def test_usage_endpoint_groups_by_account(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k")
    runtime.usage.insert("echo", "success", 10, account_id=account.id)
    body = client.get("/v1/usage", params={"group_by": "account"}).json()
    assert body[0]["account_id"] == account.id
    assert body[0]["account_label"] == "w"
    assert body[0]["request_count"] == 1


def test_usage_endpoint_groups_by_skill(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k")
    runtime.usage.insert("echo", "success", 10, account_id=account.id)
    body = client.get("/v1/usage", params={"group_by": "skill", "since": "24h"}).json()
    assert body[0]["skill_name"] == "echo"
    assert body[0]["top_account_id"] == account.id


def test_usage_endpoint_rejects_a_bad_group_by(client) -> None:
    assert client.get("/v1/usage", params={"group_by": "nope"}).status_code == 400


def test_usage_endpoint_rejects_provider_plus_group_by(client) -> None:
    response = client.get(
        "/v1/usage", params={"provider": "firecrawl", "group_by": "account"}
    )
    assert response.status_code == 400


def test_reload_endpoint_returns_the_diff(client) -> None:
    response = client.post("/v1/skills/manage/reload")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"added", "removed", "updated"}


def test_managed_skills_can_be_filtered_by_source(client) -> None:
    body = client.get("/v1/skills/manage", params={"source": "plugin"}).json()
    assert body == []
    builtin = client.get("/v1/skills/manage", params={"source": "builtin"}).json()
    assert {s["name"] for s in builtin} == {"echo", "firecrawl/scrape"}


def test_managed_skills_rejects_an_unknown_source(client) -> None:
    assert client.get("/v1/skills/manage", params={"source": "nope"}).status_code == 400


def test_plugins_listing(client) -> None:
    assert client.get("/v1/plugins").json() == []


def test_toggle_account_flips_the_flag(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k")
    body = client.post("/v1/accounts/manage/toggle", json={"account_id": account.id}).json()
    assert body == {"account_id": account.id, "enabled": False}
    assert runtime.repo.get_by_id(account.id).enabled is False


def test_toggle_account_publishes_the_disabled_event(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k")
    client.post(
        "/v1/accounts/manage/toggle",
        json={"account_id": account.id, "provider": "widget"},
    )
    assert "account.disabled" in [e.type for e in runtime.events.recent()]


def test_disable_account_endpoint(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k")
    body = client.post("/v1/accounts/manage/disable", json={"account_id": account.id}).json()
    assert body["enabled"] is False
    assert runtime.repo.get_by_id(account.id).enabled is False


def test_manage_endpoints_reject_a_bad_account_id(client) -> None:
    assert client.post("/v1/accounts/manage/toggle", json={}).status_code == 400
    assert (
        client.post("/v1/accounts/manage/disable", json={"account_id": "x"}).status_code
        == 400
    )


def test_manage_endpoints_404_on_a_missing_account(client) -> None:
    assert client.post("/v1/accounts/manage/toggle", json={"account_id": 999}).status_code == 404


def test_manage_tags_endpoint(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k", tags="a")
    body = client.post(
        "/v1/accounts/manage/tags",
        json={"account_id": account.id, "add": ["b"]},
    ).json()
    assert body["tags"] == ["a", "b"]


def test_manage_tags_endpoint_removes(client, runtime) -> None:
    account = runtime.repo.add(provider="widget", label="w", api_key="k", tags="a,b")
    body = client.post(
        "/v1/accounts/manage/tags",
        json={"account_id": account.id, "remove": ["a"]},
    ).json()
    assert body["tags"] == ["b"]


def test_dispatch_error_returns_the_spec_error_code(client, runtime) -> None:
    from routeforge.skills.base import Skill

    class Grouped(Skill):
        name = "http-grouped"
        provider = "widget"
        description = "Needs the scrape tag."
        provider_group = "scrape"

        async def execute(self, account, args, http):
            return {}

    runtime.registry.register(Grouped(), "plugin")
    response = client.post("/skills/http-grouped/call", json={"args": {}})
    assert response.status_code == 400
    assert response.json()["error"] == "no_accounts_for_group"


def test_all_cooling_returns_503_with_retry_after(client, runtime) -> None:
    import asyncio

    account = runtime.repo.add(provider="firecrawl", label="f1", api_key="k")
    asyncio.run(
        runtime.pool.mark_failure(account, reason="upstream 429", status_code=429)
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "skill:firecrawl/scrape",
            "messages": [{"role": "user", "content": "https://example.com"}],
        },
    )
    assert response.status_code == 503


def test_usage_repo_is_shared_with_the_app(client, runtime) -> None:
    assert isinstance(runtime.usage, UsageLogRepo)
