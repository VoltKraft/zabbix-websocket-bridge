"""FastAPI application entrypoint."""

import logging
import os

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .logging import configure_logging
from .middleware import RequestGuard
from .models import BatchRequest, BatchResponse, HealthResponse
from .limits import ResourceLimits
from .websocket_client import BridgeConnectionError, execute_batch

configure_logging()
logger = logging.getLogger(__name__)


async def health() -> HealthResponse:
    """Return service health."""
    return HealthResponse()


async def jsonrpc_batch(request: BatchRequest) -> BatchResponse:
    """Execute a stateless JSON-RPC batch against a supplied WebSocket target."""
    try:
        return await execute_batch(request)
    except BridgeConnectionError as exc:
        logger.error("Returning global bridge failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"ok": False, "results": {}, "errors": [str(exc)]},
        ) from exc


def create_app(settings: ResourceLimits | None = None) -> FastAPI:
    application = FastAPI(
        title="zabbix-websocket-bridge",
        description="Generic stateless HTTP-to-WebSocket JSON-RPC bridge.",
        version="0.1.0",
    )
    settings = settings if settings is not None else ResourceLimits.from_environment()
    application.add_middleware(RequestGuard, settings=settings)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Don't echo credentials, arbitrary params, or non-finite JSON values.
        return JSONResponse(status_code=422, content={"detail": "Invalid batch request"})

    application.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    application.add_api_route(
        "/api/v1/jsonrpc/batch", jsonrpc_batch, methods=["POST"], response_model=BatchResponse
    )
    return application


app = create_app()


def run() -> None:
    """Run the Uvicorn server."""
    import uvicorn

    uvicorn.run(
        "zabbix_websocket_bridge.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "info"),
        limit_concurrency=64,
        backlog=64,
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    run()
