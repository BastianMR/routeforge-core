"""FastAPI HTTP entry point."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import SkillCallRequest
from .runtime import Runtime
from .usage import parse_since

# `error_code` -> (HTTP status, response body). The spec pins the code strings.
_ERROR_STATUS = {
    "no_accounts_for_group": 400,
    "account_not_found": 400,
    "all_accounts_cooling": 503,
}


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


def create_app(runtime: Runtime) -> FastAPI:
    router = runtime.router

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [
            asyncio.create_task(runtime.usage_rollup_loop()),
            asyncio.create_task(runtime.usage_tick_loop()),
        ]
        app.state.tasks = tasks
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await runtime.http.aclose()

    app = FastAPI(title="routeforge-core", version="0.2.0", lifespan=lifespan)

    @app.get("/v1/skills")
    async def list_skills(_: Request) -> list[dict[str, Any]]:
        return [info.model_dump() for info in runtime.registry.list_all()]

    @app.post("/skills/{name}/call")
    async def call_skill(name: str, body: SkillCallRequest) -> Any:
        response = await router.call_skill(name, body.args)
        return _dispatch_result(response)

    @app.post("/v1/chat/completions")
    async def chat_completions(body: dict[str, Any]) -> Any:
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
            raise HTTPException(
                status_code=_status_for(response), detail=response.error
            )
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

    @app.get("/v1/accounts/pool")
    async def pool_snapshot() -> dict[str, Any]:
        """Per-account pool state, consumed by the TUI Accounts tab."""
        return runtime.pool.snapshot()

    @app.get("/v1/usage")
    async def usage(
        provider: str | None = None,
        skill: str | None = None,
        since: str | None = None,
        group_by: str | None = None,
        limit: int = 1000,
    ) -> Any:
        if group_by is not None or skill is not None:
            if provider is not None:
                raise HTTPException(
                    status_code=400,
                    detail="provider cannot be combined with skill or group_by",
                )
            window = parse_since(since)
            if group_by is None:
                return runtime.usage.rows(skill=skill, since=window, limit=limit)
            if group_by not in ("account", "skill"):
                raise HTTPException(
                    status_code=400, detail="group_by must be 'account' or 'skill'"
                )
            return runtime.usage.aggregate(since=window, group_by=group_by)[:limit]
        return router.usage_summary(provider).model_dump()

    @app.post("/v1/skills/manage/reload")
    async def reload_skills() -> dict[str, Any]:
        return runtime.registry.reload()

    @app.get("/v1/skills/manage")
    async def managed_skills(source: str | None = None) -> list[dict[str, Any]]:
        if source not in (None, "all", "builtin", "plugin", "manifest"):
            raise HTTPException(
                status_code=400,
                detail="source must be 'builtin', 'plugin', 'manifest', or 'all'",
            )
        return [info.model_dump() for info in runtime.registry.by_source(source)]

    @app.get("/v1/plugins")
    async def list_plugins() -> list[dict[str, Any]]:
        return [p.model_dump() for p in runtime.plugin_repo.list()]

    @app.post("/v1/accounts/manage/toggle")
    async def toggle_account(body: dict[str, Any]) -> dict[str, Any]:
        account_id = _account_id(body)
        try:
            enabled = runtime.repo.toggle_enabled(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not enabled:
            await runtime.pool.announce_disabled(account_id, body.get("provider", ""))
        return {"account_id": account_id, "enabled": enabled}

    @app.post("/v1/accounts/manage/disable")
    async def disable_account(body: dict[str, Any]) -> dict[str, Any]:
        account_id = _account_id(body)
        try:
            enabled = runtime.repo.set_enabled(account_id, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await runtime.pool.announce_disabled(account_id, body.get("provider", ""))
        return {"account_id": account_id, "enabled": enabled}

    @app.post("/v1/accounts/manage/tags")
    async def update_account_tags(body: dict[str, Any]) -> dict[str, Any]:
        account_id = _account_id(body)
        tags = list(runtime.repo.add_tags(account_id, body.get("add")))
        if body.get("remove"):
            tags = runtime.repo.remove_tags(account_id, body["remove"])
        return {"account_id": account_id, "tags": tags}

    @app.get("/v1/events")
    async def events(request: Request) -> StreamingResponse:
        # The bind address decides exposure; `_validate_bind` already refuses a
        # non-loopback bind at startup, so this is the second line of defense
        # for embedded deployments.
        settings = runtime.settings
        if not settings.allow_public and not _is_loopback(settings.http_host):
            raise HTTPException(status_code=403, detail="loopback only")

        return StreamingResponse(
            _stream(runtime, _last_event_id(request)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _status_for(response) -> int:
    if response.error_code in _ERROR_STATUS:
        return _ERROR_STATUS[response.error_code]
    if response.error and response.error.startswith("skill not found"):
        return 404
    return 502


def _dispatch_result(response) -> Any:
    if response.error and response.result is None:
        if response.error_code:
            body = {"error": response.error_code, "detail": response.error}
            headers = (
                {"Retry-After": "60"}
                if response.error_code == "all_accounts_cooling"
                else None
            )
            return JSONResponse(
                status_code=_ERROR_STATUS.get(response.error_code, 502),
                content=body,
                headers=headers,
            )
        if response.error.startswith("skill not found"):
            raise HTTPException(status_code=404, detail=response.error)
        if response.error.startswith("all accounts for provider"):
            raise HTTPException(status_code=503, detail=response.error)
        raise HTTPException(status_code=502, detail=response.error)
    return response.model_dump(exclude_none=True)


async def _stream(runtime: Runtime, last_event_id: int) -> AsyncIterator[str]:
    subscription = runtime.events.subscribe()
    heartbeat = runtime.settings.sse_heartbeat_seconds
    try:
        for event in subscription.replay_after(last_event_id):
            yield event.to_sse()
        while True:
            try:
                event = await asyncio.wait_for(subscription.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield event.to_sse()
    except asyncio.CancelledError:  # client disconnected
        raise
    finally:
        subscription.close()


def _account_id(body: dict[str, Any]) -> int:
    raw = body.get("account_id")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="account_id must be an integer") from exc


def _last_event_id(request: Request) -> int:
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")
