"""Response limits must not inherit the budgets for HTTP requests."""

import json
import logging
import traceback

import pytest
from websockets.asyncio.server import serve

from test_resource_limits import PATH, client, payload
from zabbix_websocket_bridge.models import BatchRequest
from zabbix_websocket_bridge.websocket_client import BridgeConnectionError, execute_batch


@pytest.mark.parametrize("binary", [False, True])
async def test_large_and_complex_responses_are_complete_in_one_batch(binary):
    deep = "leaf"
    for _ in range(64):
        deep = [deep]
    expected = {
        "over_64k": "a" * 105845,
        "over_1m": "b" * (1024 * 1024 + 1),
        "collection": list(range(3000)),
        # Each collection fits the old limit, but total nodes exceed 8192.
        "nodes": [[i] * 1024 for i in range(9)],
        "depth": deep,
    }
    observed = []

    async def handler(ws):
        for value in expected.values():
            message = json.loads(await ws.recv())
            observed.append(message["id"])
            response = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": value})
            await ws.send(response.encode() if binary else response)

    async with serve(handler, "127.0.0.1", 0) as server:
        body = payload(f"ws://localhost:{server.sockets[0].getsockname()[1]}/rpc")
        body["calls"] = [{"name": name, "method": "reporting.get_data"} for name in expected]
        async with client() as http:
            response = await http.post(PATH, json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["errors"] == []
        assert data["results"] == {
            name: {"ok": True, "result": value, "error": None} for name, value in expected.items()
        }
        assert observed == list(range(1, len(expected) + 1))


async def test_cumulative_responses_above_1m_with_small_individual_messages():
    value = "x" * 60000
    count = 18
    assert count * len(value) > 1024 * 1024

    async def handler(ws):
        for _ in range(count):
            message = json.loads(await ws.recv())
            response = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": value})
            assert len(response) < 64 * 1024
            await ws.send(response)

    async with serve(handler, "127.0.0.1", 0) as server:
        body = payload(f"ws://localhost:{server.sockets[0].getsockname()[1]}/rpc")
        body["calls"] = [{"name": str(i), "method": "read"} for i in range(count)]
        result = await execute_batch(BatchRequest.model_validate(body))
        assert result.ok is True
        assert len(result.results) == count
        assert all(call.ok and call.result == value for call in result.results.values())


@pytest.mark.parametrize("bad_response,expected_error", [
    ('{"secret": "response-secret",', "Invalid JSON-RPC response: response is not an object"),
    (b"\xff", "Invalid JSON-RPC response: response is not an object"),
    ('{"id": 999, "result": "response-secret"}', "Invalid JSON-RPC response: unexpected id"),
    ('{"id": 1}', "Invalid JSON-RPC response: missing result"),
    ('{"id": 1, "error": {"message": "response-secret", "data": "auth-secret"}}',
     "Target returned a JSON-RPC error"),
    ('{"id": 1, "error": "response-secret"}', "Target returned a JSON-RPC error"),
])
async def test_response_errors_are_private_and_batch_continues(bad_response, expected_error, caplog):
    caplog.set_level(logging.DEBUG)
    server_logger = logging.Logger("test.silent_server")
    server_logger.disabled = True

    async def handler(ws):
        await ws.recv()
        await ws.send(bad_response)
        message = json.loads(await ws.recv())
        await ws.send(json.dumps({"id": message["id"], "result": "response-secret"}))

    async with serve(handler, "127.0.0.1", 0, logger=server_logger) as server:
        body = payload(f"ws://user:password@localhost:{server.sockets[0].getsockname()[1]}/private-token?key=query-secret")
        body["calls"][0].update(method="auth.login", params=["auth-secret"])
        body["calls"].append({"name": "second", "method": "read"})
        result = await execute_batch(BatchRequest.model_validate(body))
        assert result.results["status"].ok is False
        assert result.results["status"].error == expected_error
        assert result.results["second"].ok is True
        assert result.results["second"].result == "response-secret"
    for secret in ("password", "private-token", "query-secret", "auth-secret", "response-secret", "auth.login", "dXNlcjpwYXNzd29yZA=="):
        assert secret not in caplog.text
        assert secret not in result.results["status"].error


async def test_connection_close_reason_is_not_exposed(caplog):
    caplog.set_level(logging.DEBUG)
    server_logger = logging.Logger("test.silent_server")
    server_logger.disabled = True

    async def handler(ws):
        await ws.recv()
        await ws.close(code=1011, reason="response-secret auth-secret")

    async with serve(handler, "127.0.0.1", 0, logger=server_logger) as server:
        request = BatchRequest.model_validate(payload(f"ws://localhost:{server.sockets[0].getsockname()[1]}/rpc"))
        with pytest.raises(BridgeConnectionError, match="^WebSocket communication failed$") as caught:
            await execute_batch(request)
    formatted = "".join(traceback.format_exception(caught.value))
    for secret in ("response-secret", "auth-secret"):
        assert secret not in caplog.text
        assert secret not in formatted
