import pytest
from pydantic import ValidationError

from zabbix_websocket_bridge.models import BatchRequest


def valid_payload() -> dict:
    return {
        "target": {"url": "wss://example.local/ws"},
        "calls": [{"name": "example", "method": "example.method", "params": []}],
    }


def test_accepts_valid_request_defaults() -> None:
    request = BatchRequest.model_validate(valid_payload())

    assert request.target.verify_tls is True
    assert request.timeout == 10


@pytest.mark.parametrize("url", ["http://example.local", "ftp://example.local", "wss://", "not-a-url"])
def test_rejects_invalid_target_urls(url: str) -> None:
    payload = valid_payload()
    payload["target"]["url"] = url

    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload)


def test_rejects_empty_calls() -> None:
    payload = valid_payload()
    payload["calls"] = []

    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload)


def test_rejects_more_than_50_calls() -> None:
    payload = valid_payload()
    payload["calls"] = [payload["calls"][0] for _ in range(51)]

    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload)


def test_rejects_timeout_above_60_seconds() -> None:
    payload = valid_payload()
    payload["timeout"] = 61

    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload)


def test_rejects_duplicate_call_names() -> None:
    payload = valid_payload()
    payload["calls"] = [
        {"name": "duplicate", "method": "first.method", "params": []},
        {"name": "duplicate", "method": "second.method", "params": []},
    ]

    with pytest.raises(ValidationError):
        BatchRequest.model_validate(payload)
