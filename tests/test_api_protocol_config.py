from __future__ import annotations

import json
from pathlib import Path

import pytest
import varint

from subnet.protocols.api_protocol import (
    ApiProtocol,
    ApiProtocolConfig,
    ApiRequestValidationContext,
    ApiRouteConfig,
    ValidatedApiRequest,
)
from subnet.protocols.pb.api_protocol_pb2 import ApiProtocolMessage


class DummyMuxedConn:
    def __init__(self, peer_id: str = "peer-remote"):
        self.peer_id = peer_id


class FakeStream:
    def __init__(self, incoming: bytes, max_read_chunk: int | None = None):
        self._incoming = bytearray(incoming)
        self._max_read_chunk = max_read_chunk
        self.written = bytearray()
        self.closed = False
        self.muxed_conn = DummyMuxedConn()

    async def read(self, size: int = -1) -> bytes:
        if not self._incoming:
            return b""
        if size < 0:
            size = len(self._incoming)
        if self._max_read_chunk is not None:
            size = min(size, self._max_read_chunk)
        data = bytes(self._incoming[:size])
        del self._incoming[:size]
        return data

    async def write(self, payload: bytes) -> None:
        self.written.extend(payload)

    async def close(self) -> None:
        self.closed = True


class FakeHost:
    def __init__(self):
        self.handler = None

    def set_stream_handler(self, _protocol_id, handler) -> None:
        self.handler = handler


class FakeHttpResponse:
    def __init__(self, chunks: tuple[bytes, ...]):
        self.chunks = chunks

    async def aread(self) -> bytes:
        return b"".join(self.chunks)

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeHttpClient:
    def __init__(self, chunks: tuple[bytes, ...]):
        self.chunks = chunks
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeHttpResponse(self.chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _framed_message(message: ApiProtocolMessage) -> bytes:
    payload = message.SerializeToString()
    return varint.encode(len(payload)) + payload


def test_api_protocol_config_reads_route_objects_from_file(tmp_path):
    config_file = tmp_path / "api_routes.json"
    config_file.write_text(
        json.dumps(
            {
                "events": {
                    "url": "http://127.0.0.1:8000/events",
                    "stream": True,
                },
            },
        ),
    )
    config = ApiProtocolConfig(
        routes={
            "events": {
                "url": "http://127.0.0.1:8000/fallback",
                "stream": False,
            },
        },
        config_file=str(config_file),
    )

    route_config = config.get_route_config("events")

    assert route_config == ApiRouteConfig(url="http://127.0.0.1:8000/events", stream=True)
    assert config.get_route("events") == "http://127.0.0.1:8000/events"


def test_api_protocol_config_parses_route_validation_fields():
    config = ApiProtocolConfig(
        routes={
            "inference": {
                "url": "http://127.0.0.1:8000/inference",
                "stream": True,
                "allowed_methods": ["POST"],
                "allowed_headers": ["content-type"],
                "max_request_bytes": 128,
                "max_response_bytes": 256,
                "timeout_seconds": 2.5,
            },
        },
    )

    assert config.get_route_config("inference") == ApiRouteConfig(
        url="http://127.0.0.1:8000/inference",
        stream=True,
        allowed_methods=("POST",),
        allowed_headers=("content-type",),
        max_request_bytes=128,
        max_response_bytes=256,
        timeout_seconds=2.5,
    )


def test_api_protocol_example_json_parses_validation_fields():
    example_file = Path(__file__).resolve().parents[1] / "subnet" / "protocols" / "config" / "api_routes.example.json"
    config = ApiProtocolConfig(config_file=str(example_file))

    inference = config.get_route_config("inference")
    events = config.get_route_config("events")

    assert inference == ApiRouteConfig(
        url="http://127.0.0.1:8000/v1/inference",
        stream=False,
        allowed_methods=("POST",),
        allowed_headers=("accept", "content-type"),
        max_request_bytes=1048576,
        max_response_bytes=10485760,
        timeout_seconds=30.0,
    )
    assert events == ApiRouteConfig(
        url="http://127.0.0.1:8000/v1/events",
        stream=True,
        allowed_methods=("GET",),
        allowed_headers=("accept",),
        max_request_bytes=0,
        max_response_bytes=10485760,
        timeout_seconds=60.0,
    )


def test_api_protocol_config_supports_legacy_url_shorthand_as_non_streaming():
    config = ApiProtocolConfig(routes={"health": "http://127.0.0.1:8000/health"})

    assert config.get_route_config("health") == ApiRouteConfig(
        url="http://127.0.0.1:8000/health",
        stream=False,
    )


@pytest.mark.asyncio
async def test_api_protocol_rejects_stream_request_for_non_streaming_route():
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "health": {
                    "url": "http://127.0.0.1:8000/health",
                    "stream": False,
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="health",
                method="GET",
                response_type=ApiProtocolMessage.STREAM,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"Route does not support streaming: health"
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_streams_when_route_allows_streaming(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"chunk-1", b"chunk-2"))
    client_kwargs = {}

    def client_factory(**kwargs):
        client_kwargs.update(kwargs)
        return http_client

    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", client_factory)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "events": {
                    "url": "http://127.0.0.1:8000/events",
                    "stream": True,
                    "timeout_seconds": 3.0,
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="events",
                method="GET",
                response_type=ApiProtocolMessage.STREAM,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"chunk-1chunk-2"
    assert http_client.calls[0]["url"] == "http://127.0.0.1:8000/events"
    assert client_kwargs["timeout"] == 3.0
    assert http_client.calls[0]["method"] == "GET"
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_exact_reads_fragmented_request_frame(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"ok",))
    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", lambda **_kwargs: http_client)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "submit": {
                    "url": "http://127.0.0.1:8000/submit",
                    "stream": False,
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="submit",
                method="POST",
                headers={"content-type": "application/json"},
                body=b'{"value": 1}',
                response_type=ApiProtocolMessage.UNARY,
            ),
        ),
        max_read_chunk=2,
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"ok"
    assert http_client.calls[0]["method"] == "POST"
    assert http_client.calls[0]["headers"] == {"content-type": "application/json"}
    assert http_client.calls[0]["content"] == b'{"value": 1}'
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_rejects_disallowed_method_before_http(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"ok",))
    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", lambda **_kwargs: http_client)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "health": {
                    "url": "http://127.0.0.1:8000/health",
                    "stream": False,
                    "allowed_methods": ["POST"],
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="health",
                method="GET",
                response_type=ApiProtocolMessage.UNARY,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"Error processing request: Method not allowed for route health: GET"
    assert http_client.calls == []
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_rejects_disallowed_header_before_http(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"ok",))
    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", lambda **_kwargs: http_client)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "health": {
                    "url": "http://127.0.0.1:8000/health",
                    "stream": False,
                    "allowed_headers": ["content-type"],
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="health",
                method="GET",
                headers={"authorization": "Bearer token"},
                response_type=ApiProtocolMessage.UNARY,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"Error processing request: Header not allowed for route health: authorization"
    assert http_client.calls == []
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_rejects_oversized_request_frame_before_body_read(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"ok",))
    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", lambda **_kwargs: http_client)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(routes={"health": "http://127.0.0.1:8000/health"}),
    )
    stream = FakeStream(varint.encode(protocol.request_validator.max_frame_bytes + 1))

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"Error processing request: API request frame exceeded maximum 1048576 bytes"
    assert http_client.calls == []
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_enforces_response_byte_cap(monkeypatch):
    http_client = FakeHttpClient(chunks=(b"abc", b"def"))
    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", lambda **_kwargs: http_client)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(
            routes={
                "health": {
                    "url": "http://127.0.0.1:8000/health",
                    "stream": False,
                    "max_response_bytes": 5,
                },
            },
        ),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="health",
                method="GET",
                response_type=ApiProtocolMessage.UNARY,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"Error processing request: API response exceeded maximum 5 bytes"
    assert http_client.calls[0]["url"] == "http://127.0.0.1:8000/health"
    assert stream.closed is True


@pytest.mark.asyncio
async def test_api_protocol_accepts_custom_request_validator(monkeypatch):
    class CustomValidator:
        @property
        def max_frame_bytes(self) -> int:
            return 1024

        @property
        def max_response_bytes(self) -> int:
            return 1024

        def validate_request(self, context: ApiRequestValidationContext) -> ValidatedApiRequest:
            return ValidatedApiRequest(
                method="POST",
                headers={"x-custom": context.headers["x-custom"]},
                body=context.body,
                timeout_seconds=1.25,
                max_response_bytes=1024,
            )

    http_client = FakeHttpClient(chunks=(b"ok",))
    client_kwargs = {}

    def client_factory(**kwargs):
        client_kwargs.update(kwargs)
        return http_client

    monkeypatch.setattr("subnet.protocols.api_protocol.httpx.AsyncClient", client_factory)
    protocol = ApiProtocol(
        FakeHost(),
        config=ApiProtocolConfig(routes={"custom": "http://127.0.0.1:8000/custom"}),
        request_validator=CustomValidator(),
    )
    stream = FakeStream(
        _framed_message(
            ApiProtocolMessage(
                route="custom",
                method="GET",
                headers={"x-custom": "value"},
                body=b"payload",
                response_type=ApiProtocolMessage.UNARY,
            ),
        ),
    )

    await protocol._handle_incoming_stream(stream)

    assert bytes(stream.written) == b"ok"
    assert client_kwargs["timeout"] == 1.25
    assert http_client.calls[0]["method"] == "POST"
    assert http_client.calls[0]["headers"] == {"x-custom": "value"}
    assert http_client.calls[0]["content"] == b"payload"
