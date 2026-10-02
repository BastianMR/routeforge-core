"""Tests for the MCP tool surface and reload notifications."""

from __future__ import annotations

import asyncio

import pytest

from routeforge.mcp_server import (
    MCP_HTTP_PATH,
    TOOL_NAMES,
    build_server,
    install_bearer_auth,
    notify_list_changed,
)
from routeforge.plugins import Plugin, PluginRepo
from routeforge.runtime import build_runtime
from routeforge.secrets import Secrets


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "mcp.db"))
    monkeypatch.setenv("ROUTE_FORGE_PLUGINS_DIR", str(tmp_path / "plugins"))
    return build_runtime()


def call(server, name: str, arguments: dict | None = None) -> dict:
    """Invoke a registered tool the way the MCP transport does."""
    return asyncio.run(
        server._tool_manager.call_tool(
            name, arguments or {}, context=None, convert_result=False
        )
    )


def tool_names(server) -> set[str]:
    listed = asyncio.run(server.list_tools())
    return {tool.name for tool in listed}


def test_exactly_seven_tools_are_advertised(runtime) -> None:
    assert tool_names(build_server(runtime)) == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 7


def test_list_changed_capability_is_declared(runtime) -> None:
    capabilities = build_server(runtime)._mcp_server.create_initialization_options().capabilities
    assert capabilities.tools is not None
    assert capabilities.tools.listChanged is True


def test_list_changed_survives_an_explicit_options_override(runtime) -> None:
    from mcp.server.lowlevel.server import NotificationOptions

    options = build_server(runtime)._mcp_server.create_initialization_options(
        NotificationOptions(tools_changed=True)
    )
    assert options.capabilities.tools.listChanged is True


def test_list_skills_includes_source_and_group(runtime) -> None:
    payload = call(build_server(runtime), "list_skills")["skills"]
    by_name = {s["name"]: s for s in payload}
    assert by_name["echo"]["source"] == "builtin"
    assert by_name["echo"]["provider_group"] is None
    assert by_name["echo"]["requires_account"] is False
    assert by_name["firecrawl/scrape"]["requires_account"] is True


def test_call_skill_returns_the_result(runtime) -> None:
    body = call(build_server(runtime), "call_skill", {"name": "echo", "args": {"x": 1}})
    assert body["result"] == {"x": 1}
    assert "isError" not in body


def test_call_skill_marks_errors(runtime) -> None:
    body = call(build_server(runtime), "call_skill", {"name": "nope", "args": {}})
    assert body["isError"] is True


def test_call_skill_reports_a_missing_pinned_account(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    body = call(
        build_server(runtime),
        "call_skill",
        {"name": "firecrawl/scrape", "args": {}, "account_label": "ghost"},
    )
    assert body["isError"] is True
    assert body["code"] == "account_not_found"


def test_list_accounts_hides_keys_and_exposes_tags(runtime) -> None:
    runtime.repo.add(
        provider="firecrawl", label="fc1", api_key="super-secret", tags=["scrape"]
    )
    payload = call(build_server(runtime), "list_accounts", {"provider": "firecrawl"})
    account = payload["accounts"]["firecrawl"][0]
    assert account["tags"] == ["scrape"]
    assert account["enabled"] is True
    assert "super-secret" not in str(payload)
    assert "api_key" not in account


def test_list_accounts_groups_every_provider(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    runtime.repo.add(provider="tavily", label="tv1", api_key="k")
    accounts = call(build_server(runtime), "list_accounts")["accounts"]
    assert set(accounts) == {"firecrawl", "tavily"}


def test_get_usage_returns_the_summary(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    runtime.usage.insert("echo", "success", 10)
    body = call(build_server(runtime), "get_usage", {"provider": "firecrawl"})
    assert body["provider"] == "firecrawl"
    assert "by_account" in body


def test_tag_account_adds_and_persists(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    body = call(
        build_server(runtime), "tag_account", {"label": "fc1", "add": ["scrape", "web"]}
    )
    assert body["tags"] == ["scrape", "web"]
    assert runtime.repo.get_by_label("fc1").tags == ["scrape", "web"]


def test_tag_account_removes(runtime) -> None:
    runtime.repo.add(
        provider="firecrawl", label="fc1", api_key="k", tags=["scrape", "web"]
    )
    body = call(
        build_server(runtime), "tag_account", {"label": "fc1", "remove": ["scrape"]}
    )
    assert body["tags"] == ["web"]


def test_tag_account_is_idempotent(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k", tags=["scrape"])
    body = call(build_server(runtime), "tag_account", {"label": "fc1", "add": ["scrape"]})
    assert body["tags"] == ["scrape"]


def test_tag_account_reports_a_missing_label(runtime) -> None:
    body = call(build_server(runtime), "tag_account", {"label": "ghost", "add": ["x"]})
    assert body["error"] == "account_not_found"
    assert body["isError"] is True


def test_tag_account_publishes_no_lifecycle_event(runtime) -> None:
    runtime.repo.add(provider="firecrawl", label="fc1", api_key="k")
    call(build_server(runtime), "tag_account", {"label": "fc1", "add": ["scrape"]})
    kinds = [e.type for e in runtime.events.recent()]
    assert "account.disabled" not in kinds
    assert "account.recovered" not in kinds


def test_list_plugins_returns_the_table_rows(runtime) -> None:
    PluginRepo(runtime.conn).upsert(
        Plugin(
            name="web-scrape",
            source="plugin",
            module="my_skills.scraper",
            attr="WebScrapeSkill",
            manifest_path="~/.routeforge/plugins/web-scrape.toml",
        )
    )
    (plugin,) = call(build_server(runtime), "list_plugins")["plugins"]
    assert plugin["name"] == "web-scrape"
    assert plugin["module"] == "my_skills.scraper"
    assert plugin["enabled"] is True


def test_reload_skills_returns_the_diff(runtime) -> None:
    body = call(build_server(runtime), "reload_skills")
    assert set(body) == {"added", "removed", "updated"}


def test_reload_publishes_the_list_changed_signal(runtime) -> None:
    runtime.registry.load_all()
    runtime.registry.reload()
    kinds = [e.type for e in runtime.events.recent()]
    assert "skill.reloaded" in kinds
    assert "mcp.tools.list_changed" in kinds


def test_notify_list_changed_is_a_noop_without_a_session(runtime) -> None:
    runtime.mcp_server = build_server(runtime)
    assert asyncio.run(notify_list_changed(runtime)) is False


def test_notify_list_changed_reaches_the_current_session(runtime) -> None:
    sent: list[bool] = []

    class FakeSession:
        async def send_tool_list_changed(self) -> None:
            sent.append(True)

    class FakeInner:
        class request_context:  # noqa: N801 - mirrors the SDK's ContextVar attr
            session = FakeSession()

    class FakeServer:
        _mcp_server = FakeInner()

    runtime.mcp_server = FakeServer()
    assert asyncio.run(notify_list_changed(runtime)) is True
    assert sent == [True]


def test_notify_list_changed_without_a_server_is_false(runtime) -> None:
    assert asyncio.run(notify_list_changed(runtime)) is False


def test_reload_skills_notifies_the_calling_session(runtime) -> None:
    """The MCP tool itself must push the notification, not just publish it."""
    sent: list[bool] = []

    class FakeSession:
        async def send_tool_list_changed(self) -> None:
            sent.append(True)

    class FakeInner:
        class request_context:  # noqa: N801 - mirrors the SDK's ContextVar attr
            session = FakeSession()

    class FakeServer:
        _mcp_server = FakeInner()

    runtime.mcp_server = FakeServer()
    body = call(build_server(runtime), "reload_skills")
    assert set(body) == {"added", "removed", "updated"}
    assert sent == [True]


def _bearer_app():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def ok(_request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route(MCP_HTTP_PATH, ok)])


def test_bearer_auth_rejects_a_request_without_a_token() -> None:
    from starlette.testclient import TestClient

    app = install_bearer_auth(_bearer_app(), "s3cret")
    client = TestClient(app)

    assert client.get(MCP_HTTP_PATH).status_code == 401
    assert (
        client.get(MCP_HTTP_PATH, headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert (
        client.get(MCP_HTTP_PATH, headers={"Authorization": "Bearer s3cret"}).status_code
        == 200
    )


def test_bearer_auth_is_not_installed_without_a_token() -> None:
    from starlette.testclient import TestClient

    client = TestClient(_bearer_app())
    assert client.get(MCP_HTTP_PATH).status_code == 200


def test_mcp_mode_binds_no_port_by_default(runtime) -> None:
    assert runtime.settings.mcp_http_port is None


def test_mcp_http_port_is_read_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROUTE_FORGE_MASTER_KEY", Secrets.generate_key())
    monkeypatch.setenv("ROUTE_FORGE_DB", str(tmp_path / "mcp2.db"))
    monkeypatch.setenv("ROUTE_FORGE_MCP_HTTP_PORT", "8788")
    assert build_runtime().settings.mcp_http_port == 8788
