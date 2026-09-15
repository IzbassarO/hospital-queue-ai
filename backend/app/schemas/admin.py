"""API keys and access log (admin only)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyInfo(BaseModel):
    id: int
    key_prefix: str = Field(description="first characters of the key, to recognise it; the key itself is never stored")
    role: str
    label: str
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["viewer", "specialist", "admin"]
    label: str = Field(min_length=1, max_length=200, description="who or what uses the key")


class ApiKeyCreated(ApiKeyInfo):
    key: str = Field(description="the API key — shown only in this response")


class AccessLogItem(BaseModel):
    id: int
    ts: dt.datetime
    key_label: str | None
    role: str | None
    method: str
    path: str
    status: int
    latency_ms: float
    client_ip: str | None
    forwarded_for: str | None
