from zabbix_websocket_bridge.jsonrpc import build_request, parse_response
from zabbix_websocket_bridge.models import JsonRpcCall


def test_build_request() -> None:
    call = JsonRpcCall(name="call", method="demo.method", params={"value": 1})

    assert build_request(call, 7) == {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "demo.method",
        "params": {"value": 1},
    }


def test_parse_success_response() -> None:
    result = parse_response({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, 1)

    assert result.ok is True
    assert result.result == {"ok": True}
    assert result.error is None


def test_parse_remote_error_response() -> None:
    result = parse_response({"jsonrpc": "2.0", "id": 1, "error": {"message": "Remote failed"}}, 1)

    assert result.ok is False
    assert result.error == "Remote failed"


def test_parse_unexpected_id_response() -> None:
    result = parse_response({"jsonrpc": "2.0", "id": 2, "result": {}}, 1)

    assert result.ok is False
    assert result.error == "Invalid JSON-RPC response: unexpected id"
