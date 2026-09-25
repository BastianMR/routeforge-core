"""Pydantic models for accounts, skills, requests, and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_serializer


class Account(BaseModel):
    id: int
    provider: str
    label: str
    api_key: str = Field(exclude=True)
    base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    last_used_at: datetime | None = None


class SkillSchemaModel(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class SkillInfo(BaseModel):
    name: str
    provider: str
    description: str
    schema_: SkillSchemaModel = Field(alias="schema")

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "description": self.description,
            "schema": self.schema_.model_dump(),
        }


class SkillCallRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class SkillCallResponse(BaseModel):
    result: dict[str, Any] | None = None
    error: str | None = None
    account_id: int | None = None
    latency_ms: int | None = None


class AccountInfo(BaseModel):
    """Account metadata without the API key."""

    id: int
    provider: str
    label: str
    base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_used_at: datetime | None = None


class UsageSummary(BaseModel):
    provider: str | None = None
    calls: int
    errors: int
    by_account: list[dict[str, Any]] = Field(default_factory=list)
    by_skill: list[dict[str, Any]] = Field(default_factory=list)
