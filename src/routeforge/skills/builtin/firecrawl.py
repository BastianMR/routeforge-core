"""Firecrawl skills."""

from __future__ import annotations

from typing import Any

import httpx

from ...models import Account, SkillSchemaModel
from ..base import Skill, SkillError

DEFAULT_BASE_URL = "https://api.firecrawl.dev"


class FirecrawlScrapeSkill(Skill):
    name = "firecrawl/scrape"
    provider = "firecrawl"
    description = "Scrape a URL with Firecrawl and return its markdown and metadata."

    def schema(self) -> SkillSchemaModel:
        return SkillSchemaModel(
            inputs={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "formats": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["markdown", "html", "rawHtml"]},
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            outputs={
                "type": "object",
                "properties": {
                    "markdown": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "additionalProperties": True,
            },
        )

    async def execute(
        self, account: Account, args: dict[str, Any], http: httpx.AsyncClient
    ) -> dict[str, Any]:
        base_url = account.base_url or DEFAULT_BASE_URL
        if not args.get("url"):
            raise SkillError("'url' is required")
        payload: dict[str, Any] = {"url": args["url"]}
        if "formats" in args:
            payload["formats"] = args["formats"]
        headers = {
            "Authorization": f"Bearer {account.api_key}",
            "Content-Type": "application/json",
        }
        response = await http.post(f"{base_url}/v1/scrape", json=payload, headers=headers)
        if response.status_code >= 400:
            raise SkillError(
                f"upstream {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        data = body.get("data", body)
        return {
            "markdown": data.get("markdown", ""),
            "metadata": data.get("metadata", {}),
        }
