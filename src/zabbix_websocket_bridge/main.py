"""FastAPI application entrypoint."""

import logging
import os

from fastapi import FastAPI, HTTPException, status

from .logging import configure_logging
from .models import BatchRequest, BatchResponse, HealthResponse
from .websocket_client import BridgeConnectionError, execute_batch

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="zabbix-websocket-bridge",
    description="Generic stateless HTTP-to-WebSocket JSON-RPC bridge.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return service health."""
    return HealthResponse()


@app.post("/api/v1/jsonrpc/batch", response_model=BatchResponse)
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


def run() -> None:
    """Run the Uvicorn server."""
    import uvicorn

    uvicorn.run(
        "zabbix_websocket_bridge.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    run()
