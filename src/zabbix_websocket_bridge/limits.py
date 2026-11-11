"""Request validation and resource budgets."""

import math
import os
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

MAX_BODY_BYTES = 128 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 8192
MAX_COLLECTION_ITEMS = 2048
MAX_MESSAGE_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def validate_url(value: str) -> str:
    """Validate WebSocket URL syntax without restricting destinations."""
    if len(value) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("target URL is too long or contains whitespace/control characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"ws", "wss"} or not value.startswith(("ws://", "wss://")):
        raise ValueError("target.url must use ws:// or wss://")
    if not parsed.hostname or parsed.port == 0:
        raise ValueError("target.url must include a valid host and port")
    if "#" in value:
        raise ValueError("target.url must not contain a fragment")
    return value


def validate_json_budget(value: object) -> object:
    """Bound JSON complexity without recursive validation of untrusted objects."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("JSON complexity limit exceeded")
        if isinstance(item, (dict, list)):
            if len(item) > MAX_COLLECTION_ITEMS:
                raise ValueError("JSON collection limit exceeded")
            if isinstance(item, dict):
                if not all(isinstance(key, str) for key in item):
                    raise ValueError("JSON object keys must be strings")
                pending.extend((child, depth + 1) for child in item.values())
            else:
                pending.extend((child, depth + 1) for child in item)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError("params must contain JSON values")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON numbers must be finite")
    return value


def check_json_depth(body: bytes) -> None:
    """Reject excessive nesting before the JSON parser allocates containers."""
    depth = 0
    quoted = escaped = False
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting limit exceeded")
        elif char in (93, 125):
            depth -= 1


class ResourceLimits(BaseModel):
    """Per-process admission and body reception limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_concurrent_batches: int = Field(default=8, ge=1, le=128)
    body_timeout: float = Field(default=10, gt=0, le=60)

    @classmethod
    def from_environment(cls) -> "ResourceLimits":
        return cls(max_concurrent_batches=os.getenv("BRIDGE_MAX_CONCURRENT_BATCHES", "8"))
