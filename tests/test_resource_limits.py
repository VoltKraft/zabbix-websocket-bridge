import asyncio
import json
import ssl
import subprocess

import httpx
import pytest
from pydantic import ValidationError
from websockets.asyncio.server import serve

from zabbix_websocket_bridge import main
from zabbix_websocket_bridge.logging import sanitize_url
from zabbix_websocket_bridge.middleware import RequestGuard
from zabbix_websocket_bridge.models import BatchRequest, BatchResponse
from zabbix_websocket_bridge.limits import MAX_BODY_BYTES, ResourceLimits
from zabbix_websocket_bridge.websocket_client import BridgeConnectionError, execute_batch

URL = "ws://monitor.example:8081/ws"
PATH = "/api/v1/jsonrpc/batch"


def payload(url=URL):
    return {"target": {"url": url}, "calls": [{"name": "status", "method": "status.read"}]}


def client(config=None):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.create_app(config or ResourceLimits())),
        base_url="http://test",
    )


async def test_translates_without_authentication_or_target_policy():
    observed = []

    async def handler(ws):
        for _ in range(2):
            message = json.loads(await ws.recv())
            observed.append(message)
            await ws.send(json.dumps({"id": message["id"], "result": message["method"]}))

    async with serve(handler, "127.0.0.1", 0) as server:
        url = f"ws://localhost:{server.sockets[0].getsockname()[1]}/rpc"
        body = payload(url)
        body["calls"].append({"name": "second", "method": "arbitrary.method", "params": [1, "value"]})
        async with client() as http:
            response = await http.post(PATH, json=body)
            assert response.status_code == 200
            assert response.json()["results"]["second"]["result"] == "arbitrary.method"
            assert (await http.get("/health")).status_code == 200
        assert observed[1]["params"] == [1, "value"]


@pytest.mark.parametrize("url", [
    "ws://host/#fragment", "ws://host:99999/",
    "ws://host:invalid/", "ws://host:0/", "ws://host/\n", "WS://host/",
    "ws://host/" + "x" * 2048,
])
def test_invalid_urls_rejected(url):
    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload(url))


async def test_body_byte_and_complexity_limits():
    async with client() as http:
        # No Content-Length: httpx sends an async stream with chunked encoding.
        async def chunks():
            yield b'{"padding":"'
            yield b"x" * MAX_BODY_BYTES

        assert (await http.post(PATH, content=chunks())).status_code == 413
        assert (await http.post(PATH, content=b"x" * (MAX_BODY_BYTES + 1))).status_code == 413
        deep = b"[" * 40 + b"0" + b"]" * 40
        assert (await http.post(PATH, content=deep)).status_code == 400
        assert (await http.post(PATH, content=deep.decode().encode("utf-16"))).status_code == 400
        body = payload()
        body["calls"][0]["params"] = list(range(2049))
        assert (await http.post(PATH, json=body)).status_code == 422
        body["calls"][0]["params"] = [[0] * 1024 for _ in range(9)]
        assert (await http.post(PATH, json=body)).status_code == 422
        body["calls"][0]["params"] = "x" * (64 * 1024)
        assert (await http.post(PATH, json=body)).status_code == 422
        body["calls"] = [
            {"name": str(i), "method": "status.read", "params": "€" * 8000} for i in range(3)
        ]
        # The received UTF-8 body fits; escaped outbound JSON exceeds the aggregate budget.
        assert (await http.post(PATH, json=body)).status_code == 422
        invalid = json.dumps(payload()).replace('"status.read"', 'NaN')
        assert (await http.post(PATH, content=invalid)).status_code == 422


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_admission_rejects_immediately_and_releases_slot(outcome, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def execute(*args):
        entered.set()
        await release.wait()
        if outcome == "error":
            raise BridgeConnectionError("test failure")
        return BatchResponse(ok=True)

    monkeypatch.setattr(main, "execute_batch", execute)
    async with client(ResourceLimits(max_concurrent_batches=1)) as http:
        first = asyncio.create_task(http.post(PATH, json=payload()))
        await asyncio.wait_for(entered.wait(), 1)
        rejected = await asyncio.wait_for(http.post(PATH, json=payload()), 1)
        assert rejected.status_code == 503
        assert rejected.headers["retry-after"] == "1"
        assert (await http.get("/health")).status_code == 200
        if outcome == "cancel":
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            release.set()
            assert (await first).status_code == (502 if outcome == "error" else 200)
        release.set()
        assert (await http.post(PATH, json=payload())).status_code != 503


async def test_guard_rejects_declared_size_without_receiving_and_releases_slow_body():
    async def inner(*args):
        pytest.fail("Rejected request reached JSON parsing")

    guard = RequestGuard(inner, ResourceLimits(max_concurrent_batches=1, body_timeout=0.01))
    scope = {"type": "http", "path": PATH, "headers": [
        (b"content-length", str(MAX_BODY_BYTES + 1).encode()),
    ]}
    sent = []

    async def send(message):
        sent.append(message)

    async def never_receive():
        pytest.fail("Oversized declared body was read")

    await guard(scope, never_receive, send)
    assert sent[0]["status"] == 413
    assert guard.active == 0
    scope["headers"].pop()
    sent.clear()

    async def stalled_receive():
        await asyncio.Event().wait()

    await guard(scope, stalled_receive, send)
    assert sent[0]["status"] == 408
    assert guard.active == 0


async def test_target_url_credentials_are_forwarded_without_bridge_auth():
    observed = []

    async def handler(ws):
        observed.append(ws.request.headers["Authorization"])
        message = json.loads(await ws.recv())
        await ws.send(json.dumps({"id": message["id"], "result": "working"}))

    async with serve(handler, "127.0.0.1", 0) as server:
        url = f"ws://user:password@localhost:{server.sockets[0].getsockname()[1]}/ws"
        async with client() as http:
            response = await http.post(PATH, json=payload(url))
            assert response.status_code == 200
            assert response.json()["results"]["status"]["result"] == "working"
        assert observed == ["Basic dXNlcjpwYXNzd29yZA=="]


async def test_timeout_closes_websocket():
    closed = asyncio.Event()

    async def handler(ws):
        await ws.recv()
        await ws.wait_closed()
        closed.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        url = f"ws://localhost:{server.sockets[0].getsockname()[1]}/ws"
        body = payload(url)
        body["timeout"] = 0.1
        with pytest.raises(BridgeConnectionError, match="Timed out"):
            await execute_batch(BatchRequest.model_validate(body))
        await asyncio.wait_for(closed.wait(), 1)


@pytest.fixture
def tls_certificate(tmp_path):
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
    ], check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, cert


@pytest.mark.parametrize("host,trusted,verify_tls,accepted", [
    ("localhost", True, True, True),
    ("127.0.0.1", True, True, False),
    ("localhost", False, True, False),
    ("localhost", False, False, True),
])
async def test_tls_verification_follows_request_setting(
    host, trusted, verify_tls, accepted, tls_certificate, monkeypatch,
):
    context, cert = tls_certificate
    sni_names = []
    context.set_servername_callback(lambda sock, name, ctx: sni_names.append(name))
    if trusted:
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))

    async def handler(ws):
        message = json.loads(await ws.recv())
        await ws.send(json.dumps({"id": message["id"], "result": "verified"}))

    async with serve(handler, "127.0.0.1", 0, ssl=context) as server:
        url = f"wss://{host}:{server.sockets[0].getsockname()[1]}/ws"
        body = payload(url)
        body["target"]["verify_tls"] = verify_tls
        request = BatchRequest.model_validate(body)
        if accepted:
            result = await execute_batch(request)
            assert result.results["status"].result == "verified"
        else:
            with pytest.raises(BridgeConnectionError):
                await execute_batch(request)
        assert sni_names == ([host] if host == "localhost" else [None])


@pytest.mark.parametrize("response", ["x" * (64 * 1024 + 1), '["\\ud800"]'])
async def test_invalid_or_oversized_target_response_is_contained(response):
    async def handler(ws):
        await ws.recv()
        await ws.send(response)

    async with serve(handler, "127.0.0.1", 0) as server:
        url = f"ws://localhost:{server.sockets[0].getsockname()[1]}/ws"
        request = BatchRequest.model_validate(payload(url))
        if len(response) > 64 * 1024:
            with pytest.raises(BridgeConnectionError):
                await execute_batch(request)
        else:
            result = await execute_batch(request)
            assert result.results["status"].ok is False


def test_logs_omit_sensitive_path_and_query():
    assert sanitize_url("wss://user:password@[::1]:443/private-token?secret=1") == "wss://[::1]:443"

