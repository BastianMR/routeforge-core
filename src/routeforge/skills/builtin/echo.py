"""Echo skill: returns the input args unchanged. Useful for smoke tests."""

from __future__ import annotations

from typing import Any

import httpx

from ...models import Account, SkillSchemaModel
from ..base import Skill


class EchoSkill(Skill):
    name = "echo"
    provider = "echo"
    description = "Returns the input arguments unchanged. Used for smoke testing the gateway."
    requires_account = False

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel(
            inputs={"type": "object", "additionalProperties": True},
            outputs={"type": "object", "additionalProperties": True},
        )

    async def execute(
        self, account: Account, args: dict[str, Any], http: httpx.AsyncClient
    ) -> dict[str, Any]:
        return dict(args)
