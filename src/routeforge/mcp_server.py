"""MCP server entry point (stdio transport).

Exposes four tools to MCP-compatible clients:
- list_skills(): return registered skills
- call_skill(name, args): dispatch a skill call
- list_accounts(provider=None): return account metadata
- get_usage(provider=None): return usage summary
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .router import Router


def build_server(router: Router) -> FastMCP:
    server = FastMCP("routeforge-core")

    @server.tool()
    def list_skills() -> dict[str, Any]:
        skills = []
        for skill in router._registry.list():
            schema = skill.schema()
            skills.append(
                {
                    "name": skill.name,
                    "provider": skill.provider,
                    "description": skill.description,
                    "schema": {"inputs": schema.inputs, "outputs": schema.outputs},
                }
            )
        return {"skills": skills}

    @server.tool()
    def call_skill(name: str, args: dict[str, Any]) -> dict[str, Any]:
        # FastMCP runs sync tools in a threadpool; we use asyncio.run via the
        # underlying event loop. The router.call_skill is async; we run it
        # synchronously here for tool simplicity.
        import asyncio

        response = asyncio.run(router.call_skill(name, args))
        return response.model_dump(exclude_none=True)

    @server.tool()
    def list_accounts(provider: str | None = None) -> dict[str, Any]:
        result = router.list_accounts(provider)
        if isinstance(result, list):
            return {"accounts": {provider or "all": [a.model_dump() for a in result]}}
        return {"accounts": {p: [a.model_dump() for a in infos] for p, infos in result.items()}}

    @server.tool()
    def get_usage(provider: str | None = None) -> dict[str, Any]:
        summary = router.usage_summary(provider)
        return summary.model_dump()

    return server
