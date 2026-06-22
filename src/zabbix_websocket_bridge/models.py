"""Pydantic models for request and response validation."""

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Target(BaseModel):
    """Target WebSocket endpoint configuration supplied per request."""

    model_config = ConfigDict(extra="forbid")

    url: str
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def validate_websocket_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError("target.url must use ws:// or wss://")
        if not parsed.netloc or not parsed.hostname:
            raise ValueError("target.url must include a valid host")
        return value


class JsonRpcCall(BaseModel):
    """A single JSON-RPC method call."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    method: str = Field(min_length=1, max_length=256)
    params: Any = Field(default_factory=list)


class BatchRequest(BaseModel):
    """Incoming batch request."""

    model_config = ConfigDict(extra="forbid")

    target: Target
    calls: list[JsonRpcCall] = Field(min_length=1, max_length=50)
    timeout: float = Field(default=10, gt=0, le=60)

    @model_validator(mode="after")
    def validate_unique_call_names(self) -> "BatchRequest":
        names = [call.name for call in self.calls]
        if len(names) != len(set(names)):
            raise ValueError("calls must use unique names")
        return self


class CallResult(BaseModel):
    """Result for an individual named call."""

    ok: bool
    result: Any | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    """Aggregated batch response."""

    ok: bool
    results: dict[str, CallResult] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health endpoint response."""

    status: Literal["ok"] = "ok"
