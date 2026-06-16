from dataclasses import dataclass
import json
import logging

import pytest
from libp2p.crypto.ed25519 import create_new_key_pair
from pydantic import BaseModel
from trio_websocket import HandshakeError

import subnet.telemetry.telemetry as telemetry_module
from subnet.telemetry.telemetry import Telemetry


def _build_telemetry(*, max_queue: int = 1000) -> Telemetry:
    return Telemetry(
        url="ws://127.0.0.1:8080/ingest",
        subnet_id=1,
        subnet_node_id=2,
        key_pair=create_new_key_pair(bytes([7]) * 32),
        max_queue=max_queue,
    )


class _ModelPayload(BaseModel):
    name: str


@dataclass
class _DataclassPayload:
    count: int


class _PeerLike:
    def to_string(self) -> str:
        return "peer-123"


class _StopTelemetry(Exception):
    pass


class _FakeExceptionGroup(Exception):
    def __init__(self, exceptions: tuple[BaseException, ...]):
        super().__init__("all attempts failed")
        self.exceptions = exceptions


@pytest.mark.trio
async def test_run_logs_websocket_handshake_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    telemetry = _build_telemetry()

    class _FailingWebsocket:
        async def __aenter__(self):
            connect_error = OSError("all attempts to connect to 127.0.0.1:8080 failed")
            connect_error.__cause__ = _FakeExceptionGroup((ConnectionRefusedError(111, "Connection refused"),))
            raise HandshakeError from connect_error

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fail_open_websocket(url: str):
        assert url == telemetry.url
        return _FailingWebsocket()

    async def stop_after_log(seconds: float) -> None:
        raise _StopTelemetry

    monkeypatch.setattr(telemetry_module, "open_websocket_url", fail_open_websocket)
    monkeypatch.setattr(telemetry_module.trio, "sleep", stop_after_log)

    with caplog.at_level(logging.ERROR, logger=telemetry_module.logger.name):
        with pytest.raises(_StopTelemetry):
            await telemetry.run()

    assert "Telemetry unavailable at ws://127.0.0.1:8080/ingest" in caplog.text
    assert "connection refused" in caplog.text
    assert "Events will remain queued and delivery will retry in 1s" in caplog.text
    assert "Traceback" not in caplog.text
    assert "HandshakeError" not in caplog.text


def test_build_payload_normalizes_values_before_queueing() -> None:
    telemetry = _build_telemetry()

    payload = telemetry._build_payload(
        "event_with_models",
        {
            "peer": _PeerLike(),
            "model": _ModelPayload(name="alice"),
            "dataclass_payload": _DataclassPayload(count=3),
            "raw": b"\xff",
        },
    )

    assert payload["event"] == "event_with_models"
    assert payload["data"] == {
        "peer": "peer-123",
        "model": {"name": "alice"},
        "dataclass_payload": {"count": 3},
        "raw": "ff",
    }
    assert "signature" in payload
    assert "pubkey" in payload

    json.loads(json.dumps(payload))
