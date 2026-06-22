"""JSON-RPC message helpers."""

from typing import Any

from .models import CallResult, JsonRpcCall


def build_request(call: JsonRpcCall, request_id: int) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request object."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": call.method,
        "params": call.params,
    }


def parse_response(payload: Any, expected_id: int) -> CallResult:
    """Parse a JSON-RPC response into an individual call result."""
    if not isinstance(payload, dict):
        return CallResult(ok=False, error="Invalid JSON-RPC response: response is not an object")

    if payload.get("id") != expected_id:
        return CallResult(ok=False, error="Invalid JSON-RPC response: unexpected id")

    if "error" in payload:
        error = payload["error"]
        if isinstance(error, dict):
            message = error.get("message") or str(error)
        else:
            message = str(error)
        return CallResult(ok=False, error=message)

    if "result" not in payload:
        return CallResult(ok=False, error="Invalid JSON-RPC response: missing result")

    return CallResult(ok=True, result=payload["result"])
