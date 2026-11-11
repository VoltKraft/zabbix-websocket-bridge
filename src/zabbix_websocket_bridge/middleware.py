"""Bound admission and body reception before FastAPI parses JSON."""

import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .limits import MAX_BODY_BYTES, ResourceLimits, check_json_depth


class RequestGuard:
    def __init__(self, app: ASGIApp, settings: ResourceLimits):
        self.app = app
        self.settings = settings
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return

        async def reject(code: int, detail: str) -> None:
            headers = {"Retry-After": "1"} if code == 503 else None
            await JSONResponse({"detail": detail}, code, headers=headers)(scope, receive, send)

        # No await between checking and claiming a slot on this worker's event loop.
        # No waiting queue: even body reception consumes a bounded slot.
        if self.active >= self.settings.max_concurrent_batches:
            await reject(503, "Bridge capacity exhausted")
            return
        self.active += 1
        try:
            lengths = [value for name, value in scope["headers"] if name == b"content-length"]
            if len(lengths) > 1 or (lengths and not lengths[0].isdigit()):
                await reject(400, "Invalid Content-Length")
                return
            if lengths and (len(lengths[0]) > 10 or int(lengths[0]) > MAX_BODY_BYTES):
                await reject(413, "Request body too large")
                return
            body = bytearray()
            try:
                async with asyncio.timeout(self.settings.body_timeout):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > MAX_BODY_BYTES:
                            await reject(413, "Request body too large")
                            return
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await reject(408, "Request body timed out")
                return
            try:
                body.decode("utf-8")  # UTF-16/32 must not bypass the byte-level depth scan.
                if b"\x00" in body:
                    raise ValueError("Invalid JSON encoding")
                check_json_depth(body)
            except ValueError:
                await reject(400, "Invalid JSON encoding or excessive nesting")
                return
            delivered = False

            async def replay() -> dict:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            self.active -= 1
