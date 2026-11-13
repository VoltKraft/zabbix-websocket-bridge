"""Pydantic models for request and response validation."""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .limits import MAX_BODY_BYTES, MAX_REQUEST_MESSAGE_BYTES, validate_json_budget, validate_url


class Target(BaseModel):
    """Target WebSocket endpoint configuration supplied per request."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def validate_websocket_url(cls, value: str) -> str:
        return validate_url(value)


class JsonRpcCall(BaseModel):
    """A single JSON-RPC method call."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    method: str = Field(min_length=1, max_length=256)
    params: JsonValue = Field(default_factory=list)

    _validate_params = field_validator("params", mode="before")(validate_json_budget)


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
        validate_json_budget([call.params for call in self.calls])
        total = 0
        for index, call in enumerate(self.calls, start=1):
            message = {"jsonrpc": "2.0", "id": index, "method": call.method, "params": call.params}
            size = len(json.dumps(message, separators=(",", ":"), allow_nan=False).encode())
            if size > MAX_REQUEST_MESSAGE_BYTES:
                raise ValueError("Serialized RPC message limit exceeded")
            total += size
        if total > MAX_BODY_BYTES:
            raise ValueError("Serialized batch limit exceeded")
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
