"""Async WebSocket JSON-RPC client."""

import asyncio
import json
import logging
import ssl
from typing import Any

import websockets
from websockets.exceptions import WebSocketException

from .jsonrpc import build_request, parse_response
from .logging import sanitize_url
from .models import BatchRequest, BatchResponse, CallResult
from .limits import MAX_MESSAGE_BYTES, MAX_RESPONSE_BYTES, validate_json_budget

logger = logging.getLogger(__name__)


class BridgeConnectionError(RuntimeError):
    """Raised when a target WebSocket connection or exchange fails globally."""


async def execute_batch(request: BatchRequest) -> BatchResponse:
    """Execute JSON-RPC calls sequentially over one transient WebSocket connection."""
    ssl_context = _ssl_context(request.target.url, request.target.verify_tls)
    safe_url = sanitize_url(request.target.url)
    logger.info("Opening WebSocket connection to target %s", safe_url)

    try:
        async with asyncio.timeout(request.timeout):
            async with websockets.connect(
                request.target.url,
                proxy=None,
                ssl=ssl_context,
                open_timeout=request.timeout,
                close_timeout=min(request.timeout, 10),
                max_queue=1,
                max_size=MAX_MESSAGE_BYTES,
                compression=None,
            ) as websocket:
                results: dict[str, CallResult] = {}
                response_bytes = 0
                for index, call in enumerate(request.calls, start=1):
                    message = build_request(call, index)
                    await websocket.send(json.dumps(message, separators=(",", ":")))
                    raw_response = await websocket.recv()
                    response_bytes += len(raw_response.encode() if isinstance(raw_response, str) else raw_response)
                    if response_bytes > MAX_RESPONSE_BYTES:
                        raise BridgeConnectionError("Target response budget exceeded")
                    results[call.name] = parse_response(_decode_json(raw_response), index)
                return BatchResponse(ok=True, results=results, errors=[])
    except TimeoutError as exc:
        logger.error("Timed out while communicating with target %s", safe_url)
        raise BridgeConnectionError("Timed out while communicating with target") from exc
    except (OSError, WebSocketException, ValueError) as exc:
        logger.error("WebSocket communication failed for target %s", safe_url)
        raise BridgeConnectionError("WebSocket communication failed") from exc


def _ssl_context(url: str, verify_tls: bool) -> ssl.SSLContext | None:
    if not url.startswith("wss://"):
        return None
    context = ssl.create_default_context()
    if not verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _decode_json(raw_response: str | bytes) -> Any:
    try:
        return validate_json_budget(json.loads(raw_response))
    except (ValueError, RecursionError):
        return None
