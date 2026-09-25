"""Skill abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..models import Account, SkillSchemaModel


class SkillError(RuntimeError):
    """Raised when a skill cannot complete the upstream call."""


class Skill(ABC):
    name: str = ""
    provider: str = ""
    description: str = ""

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel()

    @abstractmethod
    async def execute(
        self,
        account: Account,
        args: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> dict[str, Any]:
        ...
