"""FastAPI HTTP entry point."""

from __future__ import annotations

import ipaddress
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Request

from .models import SkillCallRequest
from .router import Router


def _validate_bind(settings) -> None:
    """Refuse to bind to a non-loopback address unless explicitly allowed."""
    if settings.allow_public:
        return
    try:
        ip = ipaddress.ip_address(settings.http_host)
    except ValueError:
        return  # hostname, not an IP
    if not ip.is_loopback:
        raise SystemExit(
            f"refusing to bind to non-loopback address {settings.http_host}; "
            f"set ROUTE_FORGE_ALLOW_PUBLIC=1 to override"
        )


def create_app(router: Router) -> FastAPI:
    app = FastAPI(title="routeforge-core", version="0.1.0")

    @app.get("/v1/skills")
    async def list_skills(_: Request) -> list[dict[str, Any]]:
        out = []
        for skill in router._registry.list():
            schema = skill.schema()
            out.append(
                {
                    "name": skill.name,
                    "provider": skill.provider,
                    "description": skill.description,
                    "schema": {"inputs": schema.inputs, "outputs": schema.outputs},
                }
            )
        return out

    @app.post("/skills/{name}/call")
    async def call_skill(name: str, body: SkillCallRequest) -> dict[str, Any]:
        response = await router.call_skill(name, body.args)
        if response.error and response.result is None:
            if response.error.startswith("skill not found"):
                raise HTTPException(status_code=404, detail=response.error)
            if response.error.startswith("all accounts for provider"):
                raise HTTPException(status_code=503, detail=response.error)
            raise HTTPException(status_code=502, detail=response.error)
        return response.model_dump(exclude_none=True)

    @app.post("/v1/chat/completions")
    async def chat_completions(body: dict[str, Any]) -> dict[str, Any]:
        model = body.get("model", "")
        if not isinstance(model, str) or not model.startswith("skill:"):
            raise HTTPException(
                status_code=400,
                detail="model must start with 'skill:' in routeforge-core v1",
            )
        skill_name = model[len("skill:"):]
        messages = body.get("messages") or []
        last_user = next(
            (m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"),
            None,
        )
        if last_user is None:
            raise HTTPException(status_code=400, detail="no user message found")
        content = last_user.get("content", "")
        args = {"message": content} if isinstance(content, str) else {"content": content}
        response = await router.call_skill(skill_name, args)
        if response.error:
            status = 502
            if response.error.startswith("skill not found"):
                status = 404
            elif response.error.startswith("all accounts for provider"):
                status = 503
            raise HTTPException(status_code=status, detail=response.error)
        return {
            "id": "routeforge-core",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response.result},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"account_id": response.account_id, "latency_ms": response.latency_ms},
        }

    @app.get("/v1/accounts")
    async def list_accounts(provider: str | None = None) -> dict[str, Any]:
        result = router.list_accounts(provider)
        if isinstance(result, list):
            return {provider or "all": [a.model_dump() for a in result]}
        return {p: [a.model_dump() for a in infos] for p, infos in result.items()}

    @app.get("/v1/usage")
    async def usage(provider: str | None = None) -> dict[str, Any]:
        return router.usage_summary(provider).model_dump()

    return app


_ = Annotated  # silence unused
