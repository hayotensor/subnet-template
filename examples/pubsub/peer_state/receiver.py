"""
Simple peer-state receiver example backed by ``GossipReceiverTemplate``.

This file intentionally assumes that a libp2p ``Pubsub`` service has already
been created and started. The receiver only shows the peer-state-specific
pieces: topic configuration, message validation, message handling, and latest
state tracking.

Example:

    termination_event = trio.Event()
    peer_state_receiver = PeerStateReceiver(
        pubsub=pubsub,
        termination_event=termination_event,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(peer_state_receiver.run)
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

from examples.pubsub.peer_state.config import PEER_STATE_TOPIC
from subnet.utils.pubsub.gossip_receiver_template import GossipReceiverTemplate, GossipTopicConfig

try:
    from .publisher import PeerRole, PeerStateData, ServerState
except ImportError:  # Allows running this file directly from the example dir.
    from publisher import PeerRole, PeerStateData, ServerState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeerStateReceipt:
    """Latest peer-state message observed for a peer."""

    peer_id: ID
    peer_state: PeerStateData
    received_at: float


class PeerStateReceiver:
    """
    Example peer-state receiver using ``GossipReceiverTemplate``.

    ``PeerStateReceiver.run`` delegates to the template. Incoming peer-state
    messages are validated, decoded, logged, and stored in
    ``latest_state_by_peer`` so callers can inspect peer state and role.
    """

    def __init__(
        self,
        pubsub: Pubsub,
        termination_event: trio.Event,
        *,
        topic: str = PEER_STATE_TOPIC,
        topic_validator: ValidatorFn | None = None,
        is_async_topic_validator: bool = False,
        state_timeout_seconds: float = 90.0,
        log_level: int = logging.INFO,
    ) -> None:
        self.topic = topic
        self.state_timeout_seconds = state_timeout_seconds
        self.log_level = log_level
        self.latest_state_by_peer: dict[str, PeerStateReceipt] = {}
        self._receiver = GossipReceiverTemplate(
            pubsub=pubsub,
            termination_event=termination_event,
            topics_config=[
                GossipTopicConfig(
                    topic=topic,
                    topic_handler=self.handle_peer_state,
                    topic_validator=topic_validator or self.validate_peer_state,
                    is_async_topic_validator=is_async_topic_validator,
                )
            ],
            log_level=log_level,
        )

    async def run(self) -> None:
        """Subscribe to the peer-state topic and receive until termination."""
        await self._receiver.run()

    def validate_peer_state(self, forwarder_peer_id: ID, message: rpc_pb2.Message) -> bool:
        """
        Lightweight topic validator for the example.

        Production validators can also check subnet membership, epoch, stake, or
        node identity before a message reaches ``handle_peer_state``.
        """
        peer_state = self._decode_peer_state(message)
        if peer_state is None:
            logger.warning(
                "Rejected malformed peer state from forwarder peer %s",
                forwarder_peer_id.to_string(),
            )
            return False

        return True

    async def handle_peer_state(self, from_peer_id: ID, message: rpc_pb2.Message) -> None:
        """Decode a validated peer-state message and update latest state."""
        peer_state = self._decode_peer_state(message)
        if peer_state is None:
            logger.warning("Skipping malformed peer state from peer %s", from_peer_id.to_string())
            return

        peer_key = from_peer_id.to_string()
        self.latest_state_by_peer[peer_key] = PeerStateReceipt(
            peer_id=from_peer_id,
            peer_state=peer_state,
            received_at=time.monotonic(),
        )
        logger.log(
            self.log_level,
            "Received peer state from peer=%s subnet_id=%s subnet_node_id=%s epoch=%s state=%s role=%s uid=%s",
            peer_key,
            peer_state.subnet_id,
            peer_state.subnet_node_id,
            peer_state.epoch,
            peer_state.state.name,
            peer_state.role.name,
            peer_state.uid,
        )

    def get_latest_state(self, peer_id: ID | str) -> PeerStateReceipt | None:
        """Return the latest peer-state receipt stored for ``peer_id``."""
        return self.latest_state_by_peer.get(self._peer_key(peer_id))

    def is_peer_fresh(self, peer_id: ID | str, *, now: float | None = None) -> bool:
        """Return whether ``peer_id`` has sent a peer-state update within the timeout."""
        receipt = self.get_latest_state(peer_id)
        if receipt is None:
            return False

        current_time = now if now is not None else time.monotonic()
        return current_time - receipt.received_at <= self.state_timeout_seconds

    def is_peer_online(self, peer_id: ID | str, *, now: float | None = None) -> bool:
        """Return whether the latest fresh state for ``peer_id`` is ``ONLINE``."""
        receipt = self.get_latest_state(peer_id)
        if receipt is None:
            return False

        return self.is_peer_fresh(peer_id, now=now) and receipt.peer_state.state is ServerState.ONLINE

    def peers_by_state(
        self,
        state: ServerState,
        *,
        fresh_only: bool = True,
        now: float | None = None,
    ) -> tuple[str, ...]:
        """Return peer IDs whose latest state matches ``state``."""
        return tuple(
            peer_id
            for peer_id, receipt in sorted(self.latest_state_by_peer.items())
            if receipt.peer_state.state is state and (not fresh_only or self.is_peer_fresh(peer_id, now=now))
        )

    def peers_by_role(self, role: PeerRole, *, fresh_only: bool = True, now: float | None = None) -> tuple[str, ...]:
        """Return peer IDs whose latest role matches ``role``."""
        return tuple(
            peer_id
            for peer_id, receipt in sorted(self.latest_state_by_peer.items())
            if receipt.peer_state.role is role and (not fresh_only or self.is_peer_fresh(peer_id, now=now))
        )

    def online_peers(self, *, now: float | None = None) -> tuple[str, ...]:
        """Return peer IDs whose latest fresh state is ``ONLINE``."""
        return self.peers_by_state(ServerState.ONLINE, fresh_only=True, now=now)

    @staticmethod
    def _peer_key(peer_id: ID | str) -> str:
        if isinstance(peer_id, ID):
            return peer_id.to_string()
        return peer_id

    @staticmethod
    def _decode_peer_state(message: rpc_pb2.Message) -> PeerStateData | None:
        try:
            return PeerStateData.from_json(message.data.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, AssertionError, ValueError):
            logger.debug("Unable to decode peer-state message", exc_info=True)
            return None
