"""API Protocol for communication between peers that have APIs."""

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
import json
import logging
import os
from typing import Protocol

import httpx
from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.network.stream.exceptions import (
    StreamEOF,
)
from libp2p.tools.utils import (
    info_from_p2p_addr,
)
from multiaddr import (
    Multiaddr,
)
import varint

from subnet.protocols.pb.api_protocol_pb2 import (
    ApiProtocolMessage,
)
from subnet.telemetry.telemetry import Telemetry
from subnet.utils.logging_config import configure_logging

# Configure logging
configure_logging()
logger = logging.getLogger("api_protocol/1.0.0")

# Protocol ID - this must match between all peers using this protocol
PROTOCOL_ID = "/subnet/api_protocol/1.0.0"
DEFAULT_MAX_FRAME_BYTES = 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_ALLOWED_METHODS = ("GET", "POST")
DEFAULT_ALLOWED_HEADERS = ("accept", "content-type")
MAX_STREAM_WRITE_LEN = 60 * 1024
MAX_VARINT_PREFIX_LEN = 10


@dataclass(frozen=True, slots=True)
class ApiRouteConfig:
    """Configuration for one route exposed through ``ApiProtocol``."""

    url: str
    stream: bool = False
    allowed_methods: tuple[str, ...] | None = None
    allowed_headers: tuple[str, ...] | None = None
    max_request_bytes: int | None = None
    max_response_bytes: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ApiRequestValidationContext:
    """Values available to request validation before an HTTP call is made."""

    peer_id: str
    route: str
    route_config: ApiRouteConfig
    method: str
    headers: dict[str, str]
    body: bytes
    response_type: int


@dataclass(frozen=True, slots=True)
class ValidatedApiRequest:
    """Normalized request values approved for HTTP forwarding."""

    method: str
    headers: dict[str, str]
    body: bytes | None
    timeout_seconds: float
    max_response_bytes: int


class ApiRequestValidator(Protocol):
    """Extension point for applications that need custom API bridge policy."""

    @property
    def max_frame_bytes(self) -> int:
        """Maximum inbound or outbound protobuf request frame size."""

    @property
    def max_response_bytes(self) -> int:
        """Maximum raw response bytes read from or written to a peer stream."""

    def validate_request(self, context: ApiRequestValidationContext) -> ValidatedApiRequest:
        """Validate and normalize an inbound peer request."""


class ApiProtocolValidationError(ValueError):
    """Raised when a peer API request violates local forwarding policy."""


@dataclass(frozen=True, slots=True)
class ApiRequestPolicy:
    """Default allowlist and resource-limit policy used by ``ApiProtocol``."""

    allowed_routes: tuple[str, ...] | None = None
    allowed_methods: tuple[str, ...] = DEFAULT_ALLOWED_METHODS
    allowed_headers: tuple[str, ...] = DEFAULT_ALLOWED_HEADERS
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS


class DefaultApiRequestValidator:
    """
    Default modular validation for the peer-to-HTTP bridge.

    Subnet builders can replace this object entirely by passing an
    ``ApiRequestValidator`` implementation to ``ApiProtocol``.
    """

    def __init__(self, policy: ApiRequestPolicy | None = None):
        self.policy = policy or ApiRequestPolicy()
        if self.policy.max_frame_bytes < 0:
            raise ValueError("max_frame_bytes must be non-negative")
        if self.policy.max_response_bytes < 0:
            raise ValueError("max_response_bytes must be non-negative")
        if self.policy.http_timeout_seconds <= 0:
            raise ValueError("http_timeout_seconds must be greater than zero")

    @property
    def max_frame_bytes(self) -> int:
        return self.policy.max_frame_bytes

    @property
    def max_response_bytes(self) -> int:
        return self.policy.max_response_bytes

    def validate_request(self, context: ApiRequestValidationContext) -> ValidatedApiRequest:
        allowed_routes = _normalize_optional_set(self.policy.allowed_routes, upper=False)
        if allowed_routes is not None and context.route not in allowed_routes:
            raise ApiProtocolValidationError(f"Route not allowed: {context.route}")

        method = context.method.upper()
        allowed_methods = _normalize_set(
            context.route_config.allowed_methods or self.policy.allowed_methods,
            upper=True,
        )
        if method not in allowed_methods:
            raise ApiProtocolValidationError(f"Method not allowed for route {context.route}: {method}")

        max_request_bytes = context.route_config.max_request_bytes
        if max_request_bytes is None:
            max_request_bytes = self.policy.max_frame_bytes
        if len(context.body) > max_request_bytes:
            raise ApiProtocolValidationError(
                f"Request body for route {context.route} exceeds maximum {max_request_bytes} bytes"
            )

        allowed_headers = _normalize_set(
            context.route_config.allowed_headers or self.policy.allowed_headers,
            upper=False,
        )
        headers = _filter_headers(context.headers, allowed_headers, context.route)

        timeout_seconds = context.route_config.timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = self.policy.http_timeout_seconds
        if timeout_seconds <= 0:
            raise ApiProtocolValidationError("HTTP timeout must be greater than zero")

        max_response_bytes = context.route_config.max_response_bytes
        if max_response_bytes is None:
            max_response_bytes = self.policy.max_response_bytes
        if max_response_bytes < 0:
            raise ApiProtocolValidationError("max_response_bytes must be non-negative")

        return ValidatedApiRequest(
            method=method,
            headers=headers,
            body=context.body if context.body else None,
            timeout_seconds=float(timeout_seconds),
            max_response_bytes=max_response_bytes,
        )


def _normalize_optional_set(values: Iterable[str] | None, *, upper: bool) -> frozenset[str] | None:
    if values is None:
        return None
    return _normalize_set(values, upper=upper)


def _normalize_set(values: Iterable[str], *, upper: bool) -> frozenset[str]:
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError("allowlist values must be non-empty strings")
        normalized.append(value.upper() if upper else value.lower())
    return frozenset(normalized)


def _filter_headers(headers: dict[str, str], allowed_headers: frozenset[str], route: str) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for name, value in headers.items():
        header_name = str(name).lower()
        if header_name not in allowed_headers:
            raise ApiProtocolValidationError(f"Header not allowed for route {route}: {name}")
        filtered[header_name] = str(value)
    return filtered


class ApiProtocolConfig:
    """
    Configuration for the ApiProtocol.

    Allows for in-memory routes and an optional persistent JSON config file
    that can be updated on the fly to change API routes without restarting.

    The config maps public route names used by peer calls to local or external
    HTTP URLs. Each route also declares whether it supports streaming with the
    ``stream`` flag. For example, when a remote peer calls
    ``route="inference"``, ``ApiProtocol`` looks up ``"inference"`` here and
    forwards the request to the configured URL.

    In-memory setup:
        Use ``routes`` when the route map is known when the node starts::

            config = ApiProtocolConfig(
                routes={
                    "health": {
                        "url": "http://127.0.0.1:8000/health",
                        "stream": False,
                    },
                    "inference": {
                        "url": "http://127.0.0.1:8000/v1/inference",
                        "stream": True,
                    },
                    "events": {
                        "url": "http://127.0.0.1:8000/v1/events",
                        "stream": False,
                    },
                },
            )
            api_protocol = ApiProtocol(host=host, config=config)

        Peers then call the route by name::

            response = await api_protocol.call_remote(
                destination=peer_multiaddr,
                route="inference",
                method="POST",
                headers={"content-type": "application/json"},
                body=b'{"prompt": "hello"}',
            )

    Config-file setup:
        Use ``config_file`` when you want to update routes without restarting
        the node. The file should be a JSON object whose keys are route names.
        Each value must include a target ``url`` and a boolean ``stream`` flag::

            {
              "health": {
                "url": "http://127.0.0.1:8000/health",
                "stream": false,
                "allowed_methods": ["GET"],
                "allowed_headers": ["accept"],
                "max_request_bytes": 0,
                "max_response_bytes": 4096,
                "timeout_seconds": 2.0
              },
              "inference": {
                "url": "http://127.0.0.1:8000/v1/inference",
                "stream": false,
                "allowed_methods": ["POST"],
                "allowed_headers": ["accept", "content-type"],
                "max_request_bytes": 1048576,
                "max_response_bytes": 10485760,
                "timeout_seconds": 30.0
              },
              "events": {
                "url": "http://127.0.0.1:8000/v1/events",
                "stream": true,
                "allowed_methods": ["GET"],
                "allowed_headers": ["accept"],
                "max_request_bytes": 0,
                "max_response_bytes": 10485760,
                "timeout_seconds": 60.0
              }
            }

        Then create the config with the path to that file::

            config = ApiProtocolConfig(
                config_file="api_routes.json",
            )
            api_protocol = ApiProtocol(host=host, config=config)

        ``get_route`` reads the JSON file on each lookup, so changes to the
        file are picked up at runtime. If both ``routes`` and ``config_file``
        are provided, the config file takes precedence for keys it contains and
        ``routes`` is used as the fallback.

        The legacy shorthand ``{"health": "http://127.0.0.1:8000/health"}``
        is still accepted and is treated as ``stream=False``. New route configs
        should use the explicit object format above.
    """

    def __init__(self, routes: dict = None, config_file: str = None):
        self.routes = routes or {}
        self.config_file = config_file

    def get_route(self, route_name: str) -> str | None:
        """Get the URL for a route. Checks the JSON config file first if it exists, then falls back to memory."""
        route_config = self.get_route_config(route_name)
        if route_config is None:
            return None
        return route_config.url

    def get_route_config(self, route_name: str) -> ApiRouteConfig | None:
        """Get the full route config, checking the config file before in-memory routes."""
        raw_route = self._get_file_route(route_name)
        if raw_route is not None:
            try:
                return self._parse_route_config(route_name, raw_route)
            except ValueError as e:
                logger.warning(f"Invalid ApiProtocolConfig route {route_name!r} in {self.config_file}: {e}")

        raw_route = self.routes.get(route_name)
        if raw_route is None:
            return None

        try:
            return self._parse_route_config(route_name, raw_route)
        except ValueError as e:
            logger.warning(f"Invalid ApiProtocolConfig route {route_name!r}: {e}")
            return None

    def _get_file_route(self, route_name: str):
        if self.config_file and os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    file_routes = json.load(f)
                    if isinstance(file_routes, dict) and route_name in file_routes:
                        return file_routes[route_name]
            except Exception as e:
                logger.warning(f"Failed to read/parse ApiProtocolConfig file {self.config_file}: {e}")
        return None

    @staticmethod
    def _parse_route_config(route_name: str, raw_route) -> ApiRouteConfig:
        if isinstance(raw_route, ApiRouteConfig):
            return raw_route

        if isinstance(raw_route, str):
            if not raw_route:
                raise ValueError("route URL must be a non-empty string")
            return ApiRouteConfig(url=raw_route, stream=False)

        if not isinstance(raw_route, dict):
            raise ValueError("route config must be a URL string or an object with url and stream fields")

        raw_url = raw_route.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            raise ValueError("route config requires a non-empty string url")

        raw_stream = raw_route.get("stream", False)
        if not isinstance(raw_stream, bool):
            raise ValueError("route config stream field must be true or false")

        return ApiRouteConfig(
            url=raw_url,
            stream=raw_stream,
            allowed_methods=ApiProtocolConfig._parse_string_tuple(raw_route, "allowed_methods", "methods"),
            allowed_headers=ApiProtocolConfig._parse_string_tuple(raw_route, "allowed_headers", "headers"),
            max_request_bytes=ApiProtocolConfig._parse_optional_int(raw_route, "max_request_bytes"),
            max_response_bytes=ApiProtocolConfig._parse_optional_int(raw_route, "max_response_bytes"),
            timeout_seconds=ApiProtocolConfig._parse_optional_float(raw_route, "timeout_seconds"),
        )

    @staticmethod
    def _parse_string_tuple(raw_route: dict, *keys: str) -> tuple[str, ...] | None:
        for key in keys:
            if key not in raw_route:
                continue
            raw_values = raw_route[key]
            if raw_values is None:
                return None
            if not isinstance(raw_values, list | tuple):
                raise ValueError(f"route config {key} field must be a list of strings")
            values = tuple(str(value) for value in raw_values if isinstance(value, str) and value)
            if len(values) != len(raw_values):
                raise ValueError(f"route config {key} field must contain only non-empty strings")
            return values
        return None

    @staticmethod
    def _parse_optional_int(raw_route: dict, key: str) -> int | None:
        if key not in raw_route or raw_route[key] is None:
            return None
        value = raw_route[key]
        if isinstance(value, bool):
            raise ValueError(f"route config {key} field must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"route config {key} field must be an integer") from exc
        if parsed < 0:
            raise ValueError(f"route config {key} field must be non-negative")
        return parsed

    @staticmethod
    def _parse_optional_float(raw_route: dict, key: str) -> float | None:
        if key not in raw_route or raw_route[key] is None:
            return None
        value = raw_route[key]
        if isinstance(value, bool):
            raise ValueError(f"route config {key} field must be a number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"route config {key} field must be a number") from exc
        if parsed <= 0:
            raise ValueError(f"route config {key} field must be greater than zero")
        return parsed


class ApiProtocol:
    """
    An API protocol for communication between peers. Remote peers call this protocol which
    sends out an API request to an API. This API can be another server or a local API that
    is running the logic, such as inference, training, or any other logic.

    Peers register a single api_respond handler that processes incoming requests.
    """

    def __init__(
        self,
        host: IHost,
        config: ApiProtocolConfig,
        telemetry: Telemetry | None = None,
        request_validator: ApiRequestValidator | None = None,
    ):
        """
        Initialize the ApiProtocol.

        Args:
            host: The libp2p host instance
            config: Configuration defining the API routes
            telemetry: Optional telemetry URL
            request_validator: Optional custom peer API request validator

        """
        self.host = host
        self.config = config or ApiProtocolConfig()
        self.telemetry = telemetry
        self.request_validator = request_validator or DefaultApiRequestValidator()

        # Register the protocol with the host
        self.host.set_stream_handler(PROTOCOL_ID, self._handle_incoming_stream)
        logger.info(f"ApiProtocol initialized with protocol ID: {PROTOCOL_ID}")

    async def _send_request(
        self, stream: INetStream, route: str, method: str, headers: dict, body: bytes, response_type: int
    ):
        message = ApiProtocolMessage(
            route=route,
            method=method,
            headers=headers or {},
            body=body or b"",
            response_type=response_type,
        )
        await self._write_frame(stream, message.SerializeToString())

    async def _write_frame(self, stream: INetStream, payload: bytes) -> None:
        max_frame_bytes = self.request_validator.max_frame_bytes
        if len(payload) > max_frame_bytes:
            raise ApiProtocolValidationError(f"API request frame exceeded maximum {max_frame_bytes} bytes")

        frame = varint.encode(len(payload)) + payload
        for offset in range(0, len(frame), MAX_STREAM_WRITE_LEN):
            await stream.write(frame[offset : offset + MAX_STREAM_WRITE_LEN])

    async def _read_frame(self, stream: INetStream) -> bytes:
        length_prefix = bytearray()
        while len(length_prefix) < MAX_VARINT_PREFIX_LEN:
            try:
                byte = await stream.read(1)
            except StreamEOF as exc:
                raise ApiProtocolValidationError("Stream closed while reading frame length") from exc

            if not byte:
                raise ApiProtocolValidationError("Stream closed while reading frame length")

            length_prefix.extend(byte)
            if byte[0] & 0x80 == 0:
                break
        else:
            raise ApiProtocolValidationError("Frame length prefix exceeded maximum varint size")

        msg_length = varint.decode_bytes(bytes(length_prefix))
        max_frame_bytes = self.request_validator.max_frame_bytes
        if msg_length > max_frame_bytes:
            raise ApiProtocolValidationError(f"API request frame exceeded maximum {max_frame_bytes} bytes")

        return await self._read_exact(stream, msg_length)

    async def _read_exact(self, stream: INetStream, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            try:
                chunk = await stream.read(remaining)
            except StreamEOF as exc:
                raise ApiProtocolValidationError(f"Stream closed while reading {size} byte frame") from exc

            if not chunk:
                raise ApiProtocolValidationError(f"Stream closed while reading {size} byte frame")

            chunks.append(chunk)
            remaining -= len(chunk)

        return b"".join(chunks)

    async def _read_response_until_eof(self, stream: INetStream) -> bytes:
        chunks: list[bytes] = []
        total_bytes = 0
        max_response_bytes = self.request_validator.max_response_bytes

        while True:
            try:
                chunk = await stream.read(MAX_STREAM_WRITE_LEN)
            except StreamEOF:
                break

            if not chunk:
                break

            total_bytes += len(chunk)
            if total_bytes > max_response_bytes:
                raise ApiProtocolValidationError(f"API response exceeded maximum {max_response_bytes} bytes")

            chunks.append(chunk)

        return b"".join(chunks)

    async def _write_limited_response(
        self,
        stream: INetStream,
        chunks: AsyncIterator[bytes],
        max_response_bytes: int,
    ) -> None:
        total_bytes = 0
        async for chunk in chunks:
            if not chunk:
                continue

            total_bytes += len(chunk)
            if total_bytes > max_response_bytes:
                raise ApiProtocolValidationError(f"API response exceeded maximum {max_response_bytes} bytes")

            await stream.write(chunk)

    async def _collect_limited_response(self, chunks: AsyncIterator[bytes], max_response_bytes: int) -> bytes:
        response_chunks: list[bytes] = []
        total_bytes = 0
        async for chunk in chunks:
            if not chunk:
                continue

            total_bytes += len(chunk)
            if total_bytes > max_response_bytes:
                raise ApiProtocolValidationError(f"API response exceeded maximum {max_response_bytes} bytes")

            response_chunks.append(chunk)

        return b"".join(response_chunks)

    async def call_remote(
        self,
        destination: Multiaddr,
        route: str,
        method: str = "GET",
        headers: dict = None,
        body: bytes = b"",
    ) -> bytes:
        """
        Call a remote peer's API and wait for a single unary response.
        """
        peer_id = None
        stream: INetStream | None = None
        try:
            logger.info(f"ApiProtocol call_remote: {route} {method}")
            maddr = destination
            info = info_from_p2p_addr(maddr)
            peer_id = info.peer_id

            await self.host.connect(info)
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])

            await self._send_request(stream, route, method, headers, body, ApiProtocolMessage.UNARY)

            if self.telemetry:
                await self.telemetry.emit_async("api_call_remote", route=route, method=method, peer_id=peer_id)

            return await self._read_response_until_eof(stream)
        except Exception as e:
            logger.error(f"ApiProtocol Failed to call_remote on peer {peer_id}: {e}")
            raise
        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception as close_err:
                    logger.warning(f"Failed to close ApiProtocol call_remote stream: {close_err}")

    async def stream_remote(
        self,
        destination: Multiaddr,
        route: str,
        method: str = "GET",
        headers: dict = None,
        body: bytes = b"",
    ):
        """
        Call a remote peer's API and yield the streaming response.
        """
        peer_id = None
        stream: INetStream | None = None
        try:
            logger.info(f"ApiProtocol stream_remote: {route} {method}")
            maddr = destination
            info = info_from_p2p_addr(maddr)
            peer_id = info.peer_id

            await self.host.connect(info)
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])

            await self._send_request(stream, route, method, headers, body, ApiProtocolMessage.STREAM)

            if self.telemetry:
                await self.telemetry.emit_async("api_stream_remote", route=route, method=method, peer_id=peer_id)

            total_bytes = 0
            max_response_bytes = self.request_validator.max_response_bytes
            while True:
                try:
                    chunk = await stream.read(MAX_STREAM_WRITE_LEN)
                    if not chunk:
                        break

                    total_bytes += len(chunk)
                    if total_bytes > max_response_bytes:
                        raise ApiProtocolValidationError(f"API response exceeded maximum {max_response_bytes} bytes")

                    yield chunk
                except StreamEOF:
                    break
        except Exception as e:
            logger.error(f"ApiProtocol Failed to stream_remote on peer {peer_id}: {e}")
            raise
        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception as close_err:
                    logger.warning(f"Failed to close ApiProtocol stream_remote stream: {close_err}")

    async def _handle_incoming_stream(self, stream: INetStream) -> None:
        """
        Handle incoming stream using protobuf and route to API.
        """
        try:
            peer_id = stream.muxed_conn.peer_id

            try:
                msg_bytes = await self._read_frame(stream)

                # Parse as protobuf
                message = ApiProtocolMessage()
                message.ParseFromString(msg_bytes)

                logger.info(
                    f"Received API request from {peer_id}, route: {message.route}, type: {message.response_type}"
                )

                route_config = self.config.get_route_config(message.route)

                if route_config is None:
                    logger.warning(f"Route not found: {message.route}")
                    await stream.write(b"Route not found")
                    await stream.close()
                    return

                if message.response_type == ApiProtocolMessage.STREAM and not route_config.stream:
                    logger.warning(f"Route does not support streaming: {message.route}")
                    await stream.write(f"Route does not support streaming: {message.route}".encode("utf-8"))
                    await stream.close()
                    return

                if self.telemetry:
                    await self.telemetry.emit_async(
                        "api_request_received",
                        route=message.route,
                        method=message.method,
                        peer_id=peer_id,
                        stream_requested=message.response_type == ApiProtocolMessage.STREAM,
                        stream_supported=route_config.stream,
                    )

                context = ApiRequestValidationContext(
                    peer_id=str(peer_id),
                    route=message.route,
                    route_config=route_config,
                    method=message.method,
                    headers=dict(message.headers),
                    body=bytes(message.body),
                    response_type=message.response_type,
                )
                validated = self.request_validator.validate_request(context)

                async with httpx.AsyncClient(timeout=validated.timeout_seconds) as client:
                    async with client.stream(
                        method=validated.method,
                        url=route_config.url,
                        headers=validated.headers,
                        content=validated.body,
                    ) as resp:
                        if message.response_type == ApiProtocolMessage.UNARY:
                            response_body = await self._collect_limited_response(
                                resp.aiter_bytes(), validated.max_response_bytes
                            )
                            await stream.write(response_body)
                        elif message.response_type == ApiProtocolMessage.STREAM:
                            await self._write_limited_response(
                                stream,
                                resp.aiter_bytes(),
                                validated.max_response_bytes,
                            )
                        else:
                            logger.warning("Unknown response type requested.")

            except Exception as proto_err:
                logger.warning(f"Failed to process API request: {proto_err}")
                await stream.write(f"Error processing request: {proto_err}".encode("utf-8"))

            await stream.close()
        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            try:
                await stream.close()
            except Exception:
                pass
