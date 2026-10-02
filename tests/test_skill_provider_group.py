"""Tests for `SkillInfo.provider_group` and the `Skill.info` property."""

from __future__ import annotations

import httpx

from routeforge.models import SkillSchemaModel
from routeforge.skills.base import Skill
from routeforge.skills.builtin.echo import EchoSkill
from routeforge.skills.builtin.firecrawl import FirecrawlScrapeSkill


class GroupedSkill(Skill):
    name = "widget/lookup"
    provider = "widget"
    description = "Looks up a widget."
    provider_group = "lookup"

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel(inputs={"type": "object"}, outputs={"type": "object"})

    async def execute(self, account, args, http: httpx.AsyncClient) -> dict:
        return {}


def test_info_defaults_to_no_group_and_requires_an_account() -> None:
    info = FirecrawlScrapeSkill().info
    assert info.provider_group is None
    assert info.requires_account is True
    assert info.source == "builtin"


def test_info_reports_the_declared_group() -> None:
    info = GroupedSkill().info
    assert info.provider_group == "lookup"
    assert info.name == "widget/lookup"
    assert info.source == "builtin"


def test_info_reports_requires_account_false_for_echo() -> None:
    assert EchoSkill().info.requires_account is False


def test_info_serializes_source_and_group() -> None:
    dumped = GroupedSkill().info.model_dump()
    assert dumped["provider_group"] == "lookup"
    assert dumped["source"] == "builtin"
    assert dumped["requires_account"] is True
    assert "schema" in dumped


def test_info_schema_is_the_declared_one() -> None:
    dumped = FirecrawlScrapeSkill().info.model_dump()
    assert "url" in dumped["schema"]["inputs"]["properties"]


def test_every_builtin_exposes_info() -> None:
    for skill in (EchoSkill(), FirecrawlScrapeSkill()):
        assert skill.info.name == skill.name
        assert skill.info.provider == skill.provider
