"""MCP server entry point (stdio, plus an optional streamable-HTTP transport).

Seven tools are exposed:
- list_skills(): registered skills, with source and provider_group
- call_skill(name, args, account_label=None): dispatch a skill call
- list_accounts(provider=None): account metadata, never API keys
- get_usage(provider=None): aggregated usage
- reload_skills(): re-scan every source and return the diff
- list_plugins(): loaded plugins with their manifest paths
- tag_account(label, add=None, remove=None): manage account tags
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions

from .models import AccountInfo, SkillInfo
from .runtime import Runtime

LIST_CHANGED_EVENT = "mcp.tools.list_changed"

# Exactly the seven tool names the spec requires, in a stable order.
TOOL_NAMES = (
    "list_skills",
    "call_skill",
    "list_accounts",
    "get_usage",
    "reload_skills",
    "list_plugins",
    "tag_account",
)

MCP_HTTP_PATH = "/mcp"


def _declare_list_changed(server: FastMCP) -> FastMCP:
    """Force `capabilities.tools.listChanged = true` on the handshake.

    `FastMCP` builds `InitializationOptions` with a default `NotificationOptions`,
    and its constructor does not accept an override, so `listChanged` would be
    advertised as false and clients would never learn about plugin reloads.
    Patching the instance keeps the declared capability honest without forking
    the SDK. Drop this once the SDK exposes the option on `FastMCP`.
    """
    inner = server._mcp_server
    original = inner.create_initialization_options

    def create_initialization_options(
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    ):
        return original(
            notification_options or NotificationOptions(tools_changed=True),
            experimental_capabilities,
        )

    inner.create_initialization_options = create_initialization_options  # type: ignore[method-assign]
    return server


def build_server(runtime: Runtime) -> FastMCP:
    router = runtime.router
    server = _declare_list_changed(FastMCP("routeforge-core"))

    @server.tool()
    def list_skills() -> dict[str, Any]:
        return {"skills": [info.model_dump() for info in runtime.registry.list_all()]}

    @server.tool()
    async def call_skill(
        name: str,
        args: dict[str, Any],
        account_label: str | None = None,
    ) -> dict[str, Any]:
        response = await router.call_skill(name, args, account_label=account_label)
        body = response.model_dump(exclude_none=True)
        if response.error:
            body["isError"] = True
            if response.error_code:
                body["code"] = response.error_code
        return body

    @server.tool()
    def list_accounts(provider: str | None = None) -> dict[str, Any]:
        result = router.list_accounts(provider)
        if isinstance(result, list):
            return {"accounts": {provider or "all": [_account(a) for a in result]}}
        return {"accounts": {p: [_account(a) for a in infos] for p, infos in result.items()}}

    @server.tool()
    def get_usage(provider: str | None = None) -> dict[str, Any]:
        return router.usage_summary(provider).model_dump()

    @server.tool()
    async def reload_skills() -> dict[str, Any]:
        """Re-scan every source and tell connected sessions the tool list moved."""
        diff = runtime.registry.reload()
        await notify_list_changed(runtime)
        return diff

    @server.tool()
    def list_plugins() -> dict[str, Any]:
        return {"plugins": [p.model_dump() for p in runtime.plugin_repo.list()]}

    @server.tool()
    def tag_account(
        label: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]:
        account = runtime.repo.get_by_label(label)
        if account is None:
            return {"error": "account_not_found", "label": label, "isError": True}
        tags = runtime.repo.add_tags(account.id, add)
        if remove:
            tags = runtime.repo.remove_tags(account.id, remove)
        # Tags are not lifecycle events, so no account.* event is published.
        return {"label": label, "tags": tags}

    return server


def _account(info: AccountInfo) -> dict[str, Any]:
    return info.model_dump()


def _skill(info: SkillInfo) -> dict[str, Any]:
    return info.model_dump()


def install_bearer_auth(app: Any, token: str) -> Any:
    """Wrap a streamable-HTTP app so every request carries the bearer token."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            if request.headers.get("Authorization", "") != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(BearerMiddleware)
    return app


def run_stdio(runtime: Runtime) -> None:
    asyncio.run(run_stdio_async(runtime))


async def run_stdio_async(runtime: Runtime) -> None:
    server = build_server(runtime)
    runtime.mcp_server = server
    await server.run_stdio_async()


def run_http(runtime: Runtime, port: int, token: str | None = None) -> None:
    """Serve MCP over streamable HTTP at `/mcp`.

    Only called when `ROUTE_FORGE_MCP_HTTP_PORT` is set; stdio stays available.
    """
    import uvicorn

    server = build_server(runtime)
    runtime.mcp_server = server
    app = server.streamable_http_app()
    if token:
        install_bearer_auth(app, token)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


async def notify_list_changed(runtime: Runtime) -> bool:
    """Push `notifications/tools/list_changed` to the calling session.

    `send_tool_list_changed` lives on `ServerSession`, and the low-level server
    only exposes the current session through a ContextVar that is populated
    *while a request is being handled*. So this only works from inside a tool
    call — which is exactly where a reload is triggered from MCP. Returns False
    when there is no session in scope.

    Reloads triggered over HTTP publish `skill.reloaded` and
    `mcp.tools.list_changed` on the event bus instead, so SSE clients (the TUI,
    `routeforge events`) still see them.
    """
    server = getattr(runtime, "mcp_server", None)
    inner = getattr(server, "_mcp_server", None)
    if inner is None:
        return False
    try:
        session = inner.request_context.session
    except LookupError:
        return False
    await session.send_tool_list_changed()
    return True
