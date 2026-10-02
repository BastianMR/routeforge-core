"""Tests for usage tracking: row shape, aggregation, rollup, and privacy."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from routeforge.rotation import RoundRobinPool
from routeforge.router import Router
from routeforge.skills.base import Skill, SkillError
from routeforge.skills.registry import SkillRegistry
from routeforge.usage import UsageLogRepo, is_error, parse_since, status_label


class Good(Skill):
    name = "good"
    provider = "widget"
    description = "Returns its args."

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        return dict(args)


class Boom(Skill):
    name = "boom"
    provider = "widget"
    description = "Always fails with a 503."

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        raise SkillError("upstream 503: nope")


class Kaboom(Skill):
    name = "kaboom"
    provider = "widget"
    description = "Raises something that is not a SkillError."

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        raise RuntimeError("socket exploded")


def _router(repo, conn, usage: UsageLogRepo) -> tuple[Router, httpx.AsyncClient]:
    registry = SkillRegistry()
    registry.discover_builtin()
    registry.register(Good(), "plugin")
    registry.register(Boom(), "plugin")
    registry.register(Kaboom(), "plugin")
    pool = RoundRobinPool(repo, default_cooldown_seconds=60)
    http = httpx.AsyncClient(timeout=5.0)
    return Router(repo, pool, registry, http, conn, usage=usage), http


def test_status_label_vocabulary() -> None:
    assert status_label(200) == "success"
    assert status_label(None) == "success"
    assert status_label(404) == "error_4xx"
    assert status_label(429) == "error_4xx"
    assert status_label(500) == "error_5xx"
    assert status_label(503) == "error_5xx"
    assert is_error("error_4xx")
    assert not is_error("success")


def test_parse_since_windows() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    assert parse_since("1h") is not None
    assert abs((now - parse_since("1h")).total_seconds() - 3600) < 5
    assert abs((now - parse_since("30m")).total_seconds() - 1800) < 5
    assert abs((now - parse_since("7d")).total_seconds() - 604800) < 5
    assert parse_since(None) is None
    assert parse_since("nonsense") is None


def test_row_shape_matches_the_spec(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    account = repo.add(provider="firecrawl", label="fc", api_key="k")
    usage.insert(
        skill_name="firecrawl/scrape",
        status="success",
        latency_ms=350,
        account_id=account.id,
        provider_group="scrape",
        tags=["scrape", "web"],
    )
    (row,) = usage.rows()
    assert row["skill_name"] == "firecrawl/scrape"
    assert row["status"] == "success"
    assert row["latency_ms"] == 350
    assert row["account_id"] == account.id
    assert row["provider_group"] == "scrape"
    assert row["tags"] == ["scrape", "web"]
    assert row["error"] is None
    assert row["ts"]
    assert row["id"]


@pytest.mark.asyncio
async def test_successful_dispatch_is_logged(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    account = repo.add(provider="widget", label="w", api_key="k")
    router, http = _router(repo, conn, usage)

    response = await router.call_skill("good", {"x": 1})
    assert response.error is None

    (row,) = usage.rows()
    assert row["skill_name"] == "good"
    assert row["status"] == "success"
    assert row["account_id"] == account.id
    assert row["latency_ms"] is not None
    await http.aclose()


@pytest.mark.asyncio
async def test_failed_dispatch_is_logged_with_error_text(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    account = repo.add(provider="widget", label="w", api_key="k")
    router, http = _router(repo, conn, usage)

    response = await router.call_skill("boom", {})
    assert response.error is not None
    (row,) = usage.rows()
    assert row["status"] == "error_5xx"
    assert row["error"] == "upstream 503: nope"
    assert row["account_id"] == account.id
    await http.aclose()


@pytest.mark.asyncio
async def test_unexpected_exception_is_logged_as_error_network(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    repo.add(provider="widget", label="w", api_key="k")
    router, http = _router(repo, conn, usage)

    await router.call_skill("kaboom", {})
    (row,) = usage.rows()
    assert row["status"] == "error_network"
    await http.aclose()


@pytest.mark.asyncio
async def test_ephemeral_dispatch_has_null_account_id(conn) -> None:
    usage = UsageLogRepo(conn)
    router, http = _router(_NullRepo(), conn, usage)

    await router.call_skill("echo", {"a": 1})
    (row,) = usage.rows()
    assert row["account_id"] is None
    await http.aclose()


class _NullRepo:
    """Minimal repo stub for the no-accounts path."""

    def list_by_provider(self, provider: str) -> list:
        return []

    def list_by_tag(self, tag: str) -> list:
        return []

    def touch(self, account_id: int) -> None:
        pass


def test_aggregate_by_account_matches_manual_counts(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    first = repo.add(provider="widget", label="one", api_key="k")
    second = repo.add(provider="widget", label="two", api_key="k")
    usage.insert("echo", "success", 100, account_id=first.id)
    usage.insert("echo", "error_4xx", 200, account_id=first.id)
    usage.insert("echo", "success", 300, account_id=second.id)

    rows = usage.aggregate(group_by="account")
    assert rows == [
        {
            "account_id": first.id,
            "account_label": "one",
            "request_count": 2,
            "error_count": 1,
            "avg_latency_ms": 150.0,
        },
        {
            "account_id": second.id,
            "account_label": "two",
            "request_count": 1,
            "error_count": 0,
            "avg_latency_ms": 300.0,
        },
    ]


def test_aggregate_by_skill_reports_the_top_account(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    first = repo.add(provider="widget", label="one", api_key="k")
    second = repo.add(provider="widget", label="two", api_key="k")
    third = repo.add(provider="widget", label="three", api_key="k")
    usage.insert("a", "success", 10, account_id=first.id)
    usage.insert("a", "success", 10, account_id=second.id)
    usage.insert("a", "success", 10, account_id=first.id)
    usage.insert("b", "error_5xx", 40, account_id=third.id)

    rows = {r["skill_name"]: r for r in usage.aggregate(group_by="skill")}
    assert rows["a"]["request_count"] == 3
    assert rows["a"]["top_account_id"] == first.id
    assert rows["a"]["avg_latency_ms"] == 10.0
    assert rows["b"]["error_count"] == 1
    assert rows["b"]["top_account_id"] == third.id


def test_aggregate_without_group_by_returns_rows(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("echo", "success", 10)
    rows = usage.aggregate()
    assert rows[0]["skill_name"] == "echo"


def test_aggregate_rejects_an_unknown_group_by(conn) -> None:
    usage = UsageLogRepo(conn)
    with pytest.raises(ValueError, match="group_by"):
        usage.aggregate(group_by="nonsense")


def test_filter_by_skill_and_window(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("keep", "success", 10)
    usage.insert("drop", "success", 10)
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
    usage.insert("keep", "success", 10, ts=old)

    assert {r["skill_name"] for r in usage.rows(skill="keep")} == {"keep"}
    recent = usage.rows(since=parse_since("1h"))
    assert len(recent) == 2


def test_rows_are_capped_at_one_thousand(conn) -> None:
    usage = UsageLogRepo(conn)
    for i in range(1005):
        conn.execute(
            "INSERT INTO usage_log (skill_name, status, latency_ms) VALUES (?, 'success', 1)",
            ("echo",),
        )
        assert i < 1005
    assert len(usage.rows()) == 1000


def test_rollup_fills_usage_daily(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    account = repo.add(provider="widget", label="w", api_key="k")
    for latency in (10, 20, 30, 40):
        usage.insert("echo", "success", latency, account_id=account.id)
    usage.insert("echo", "error_5xx", 50, account_id=account.id)

    assert usage.rollup() == 2
    rows = conn.execute(
        "SELECT * FROM usage_daily ORDER BY status"
    ).fetchall()
    by_status = {r["status"]: r for r in rows}
    assert by_status["success"]["request_count"] == 4
    assert by_status["success"]["avg_latency_ms"] == 25.0
    assert by_status["success"]["p95_latency_ms"] == 40.0
    assert by_status["error_5xx"]["error_count"] == 1


def test_rollup_is_idempotent(repo, conn) -> None:
    usage = UsageLogRepo(conn)
    account = repo.add(provider="widget", label="w", api_key="k")
    usage.insert("echo", "success", 10, account_id=account.id)
    usage.rollup()
    usage.rollup()
    (count,) = conn.execute("SELECT COUNT(*) AS n FROM usage_daily").fetchone()
    assert count == 1


def test_prune_deletes_old_rows(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("old", "success", 10, ts=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=90))
    usage.insert("new", "success", 10)
    removed = usage.prune(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30))
    assert removed == 1
    assert [r["skill_name"] for r in usage.rows()] == ["new"]


def test_counts_reports_requests_and_errors(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("echo", "success", 10)
    usage.insert("echo", "error_4xx", 10)
    assert usage.counts() == (2, 1)


def test_privacy_no_bodies_are_stored(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("echo", "success", 10, error=None)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(usage_log)").fetchall()}
    for forbidden in ("request_body", "response_body", "api_key", "args"):
        assert forbidden not in columns


def test_tags_round_trip_as_json(conn) -> None:
    usage = UsageLogRepo(conn)
    usage.insert("echo", "success", 10, tags=["a", "b"])
    stored = conn.execute("SELECT tags FROM usage_log").fetchone()["tags"]
    assert json.loads(stored) == ["a", "b"]
