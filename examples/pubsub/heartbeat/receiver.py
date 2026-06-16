"""
Simple heartbeat receiver example backed by ``GossipReceiverTemplate``.

This file intentionally assumes that a libp2p ``Pubsub`` service has already
been created and started. The receiver only shows the heartbeat-specific pieces:
topic configuration, message validation, message handling, and last-seen state.

Example:

    termination_event = trio.Event()
    heartbeat_receiver = HeartbeatReceiver(
        pubsub=pubsub,
        termination_event=termination_event,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(heartbeat_receiver.run)
        ...
        termination_event.set()

"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from libp2p.peer.id import ID
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub, ValidatorFn
from pydantic import ValidationError
import trio

from examples.pubsub.heartbeat.config import HEARTBEAT_TOPIC
from subnet.utils.pubsub.gossip_receiver_template import GossipReceiverTemplate, GossipTopicConfig

try:
    from .publisher import HeartbeatData
except ImportError:  # Allows running this file directly from the example dir.
    from publisher import HeartbeatData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HeartbeatReceipt:
    """Last heartbeat observed for a peer."""

    peer_id: ID
    heartbeat: HeartbeatData
    received_at: float


class HeartbeatReceiver:
    """
    Example heartbeat receiver using ``GossipReceiverTemplate``.

    ``HeartbeatReceiver.run`` delegates to the template. Incoming heartbeat
    messages are validated, decoded, logged, and stored in
    ``last_heartbeat_by_peer`` so callers can ask whether a peer is still
    considered alive.
    """

    def __init__(
        self,
        pubsub: Pubsub,
        termination_event: trio.Event,
        *,
        topic: str = HEARTBEAT_TOPIC,
        topic_validator: ValidatorFn | None = None,
        is_async_topic_validator: bool = False,
        heartbeat_timeout_seconds: float = 90.0,
        log_level: int = logging.INFO,
    ) -> None:
        self.topic = topic
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.log_level = log_level
        self.last_heartbeat_by_peer: dict[str, HeartbeatReceipt] = {}
        self._receiver = GossipReceiverTemplate(
            pubsub=pubsub,
            termination_event=termination_event,
            topics_config=[
                GossipTopicConfig(
                    topic=topic,
                    topic_handler=self.handle_heartbeat,
                    topic_validator=topic_validator or self.validate_heartbeat,
                    is_async_topic_validator=is_async_topic_validator,
                )
            ],
            log_level=log_level,
        )

    async def run(self) -> None:
        """Subscribe to the heartbeat topic and receive until termination."""
        await self._receiver.run()

    def validate_heartbeat(self, forwarder_peer_id: ID, message: rpc_pb2.Message) -> bool:
        """
        Lightweight topic validator for the example.

        Production validators can also check subnet membership, epoch, stake, or
        node identity before a message reaches ``handle_heartbeat``.
        """
        heartbeat = self._decode_heartbeat(message)
        if heartbeat is None:
            logger.warning(
                "Rejected malformed heartbeat from forwarder peer %s",
                forwarder_peer_id.to_string(),
            )
            return False

        return True

    async def handle_heartbeat(self, from_peer_id: ID, message: rpc_pb2.Message) -> None:
        """Decode a validated heartbeat and update last-seen state."""
        heartbeat = self._decode_heartbeat(message)
        if heartbeat is None:
            logger.warning("Skipping malformed heartbeat from peer %s", from_peer_id.to_string())
            return

        peer_key = from_peer_id.to_string()
        self.last_heartbeat_by_peer[peer_key] = HeartbeatReceipt(
            peer_id=from_peer_id,
            heartbeat=heartbeat,
            received_at=time.monotonic(),
        )
        logger.log(
            self.log_level,
            "Received heartbeat from peer=%s subnet_id=%s subnet_node_id=%s epoch=%s uid=%s",
            peer_key,
            heartbeat.subnet_id,
            heartbeat.subnet_node_id,
            heartbeat.epoch,
            heartbeat.uid,
        )

    def get_last_heartbeat(self, peer_id: ID | str) -> HeartbeatReceipt | None:
        """Return the last heartbeat receipt stored for ``peer_id``."""
        return self.last_heartbeat_by_peer.get(self._peer_key(peer_id))

    def is_peer_alive(self, peer_id: ID | str, *, now: float | None = None) -> bool:
        """
        Return whether ``peer_id`` has sent a heartbeat within the timeout.

        This is the minimal heartbeat liveness concept: receiving a heartbeat
        refreshes the peer's timestamp, and absence beyond the timeout marks the
        peer as stale.
        """
        receipt = self.get_last_heartbeat(peer_id)
        if receipt is None:
            return False

        current_time = now if now is not None else time.monotonic()
        return current_time - receipt.received_at <= self.heartbeat_timeout_seconds

    def alive_peers(self, *, now: float | None = None) -> tuple[str, ...]:
        """Return peer IDs that are currently alive according to the timeout."""
        return tuple(
            peer_id
            for peer_id in sorted(self.last_heartbeat_by_peer)
            if self.is_peer_alive(peer_id, now=now)
        )

    @staticmethod
    def _peer_key(peer_id: ID | str) -> str:
        if isinstance(peer_id, ID):
            return peer_id.to_string()
        return peer_id

    @staticmethod
    def _decode_heartbeat(message: rpc_pb2.Message) -> HeartbeatData | None:
        try:
            return HeartbeatData.from_json(message.data.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, AssertionError, ValueError):
            logger.debug("Unable to decode heartbeat message", exc_info=True)
            return None
