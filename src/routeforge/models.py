"""Pydantic models for accounts, skills, requests, and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer

SkillSource = Literal["builtin", "plugin", "manifest"]


class Account(BaseModel):
    id: int
    provider: str
    label: str
    api_key: str = Field(exclude=True)
    base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: datetime
    last_used_at: datetime | None = None


class SkillSchemaModel(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class SkillInfo(BaseModel):
    """Everything a client needs to reason about a skill before calling it."""

    name: str
    provider: str
    description: str
    schema_: SkillSchemaModel = Field(alias="schema")
    source: SkillSource = "builtin"
    provider_group: str | None = None
    requires_account: bool = True

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "description": self.description,
            "schema": self.schema_.model_dump(),
            "source": self.source,
            "provider_group": self.provider_group,
            "requires_account": self.requires_account,
        }


class SkillCallRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class SkillCallResponse(BaseModel):
    result: dict[str, Any] | None = None
    error: str | None = None
    account_id: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None


class AccountInfo(BaseModel):
    """Account metadata without the API key."""

    id: int
    provider: str
    label: str
    base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    last_used_at: datetime | None = None


class UsageSummary(BaseModel):
    provider: str | None = None
    calls: int
    errors: int
    by_account: list[dict[str, Any]] = Field(default_factory=list)
    by_skill: list[dict[str, Any]] = Field(default_factory=list)


class PluginInfo(BaseModel):
    """A plugin row, as reported by the CLI, HTTP, and MCP surfaces."""

    name: str
    source: SkillSource = "plugin"
    module: str | None = None
    attr: str | None = None
    manifest_path: str | None = None
    enabled: bool = True
    loaded_at: str | None = None
    error: str | None = None
    missing_source: bool = False
