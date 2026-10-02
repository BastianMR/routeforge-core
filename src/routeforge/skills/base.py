"""Skill abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..models import Account, SkillInfo, SkillSchemaModel, SkillSource


class SkillError(RuntimeError):
    """Raised when a skill cannot complete the upstream call."""


class Skill(ABC):
    name: str = ""
    provider: str = ""
    description: str = ""
    requires_account: bool = True
    # When set, dispatch rotates across every account carrying this tag instead
    # of matching on `provider` alone.
    provider_group: str | None = None
    source: SkillSource = "builtin"

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel()

    @property
    def info(self) -> SkillInfo:
        return SkillInfo(
            name=self.name,
            provider=self.provider,
            description=self.description,
            schema=self.schema(),
            source=self.source,
            provider_group=self.provider_group,
            requires_account=self.requires_account,
        )

    @abstractmethod
    async def execute(
        self,
        account: Account,
        args: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> dict[str, Any]:
        ...
