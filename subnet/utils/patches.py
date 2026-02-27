"""
Monkey patches for libp2p to improve stability.

These patches fix race conditions and unhandled exceptions in the upstream library.

This is a temporary solution until the upstream library issues are fixed.
"""

import logging
from typing import List

from libp2p.abc import (
    IHost,
    INetStream,
    IPeerStore,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)
import libp2p.identity.identify_push.identify_push as identify_push
from libp2p.network.stream.exceptions import StreamReset
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.pubsub.exceptions import NoPubsubAttached
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from multiaddr import (
    Multiaddr,
)

logger = logging.getLogger(__name__)


def patch_get_in_topic_gossipsub_peers_from_minus():
    """
    Fix KeyError in GossipSub._get_in_topic_gossipsub_peers_from_minus.

    Race condition: peer is in peer_topics but removed from peer_protocol
    during disconnect. Use .get() for safe access.
    """

    def safe_get_in_topic_gossipsub_peers_from_minus(
        self: GossipSub,
        topic: str,
        num_to_select: int,
        minus: List[ID],
        backoff_check: bool = False,
    ) -> List[ID]:
        if self.pubsub is None:
            raise NoPubsubAttached

        # Use .get() to safely check protocol participation
        from libp2p.pubsub.gossipsub import PROTOCOL_ID, PROTOCOL_ID_V11, PROTOCOL_ID_V12

        gossipsub_peers_in_topic = {
            peer_id
            for peer_id in self.pubsub.peer_topics[topic]
            if self.peer_protocol.get(peer_id) in (PROTOCOL_ID, PROTOCOL_ID_V11, PROTOCOL_ID_V12)
        }
        if backoff_check:
            gossipsub_peers_in_topic = {
                peer_id for peer_id in gossipsub_peers_in_topic if self._check_back_off(peer_id, topic) is False
            }
        return self.select_from_minus(num_to_select, list(gossipsub_peers_in_topic), minus)

    GossipSub._get_in_topic_gossipsub_peers_from_minus = safe_get_in_topic_gossipsub_peers_from_minus


def patch_write_msg():
    """
    Patch fixes an issue in Pubsub.write_msg where it crashes a peer with StreamReset when another peer is disconnected.
    """
    _orig_write_msg = Pubsub.write_msg

    async def safe_write_msg(self: Pubsub, stream: INetStream, rpc_msg) -> bool:
        try:
            return await _orig_write_msg(self, stream, rpc_msg)
        except StreamReset:
            try:
                peer_id = stream.muxed_conn.peer_id
            except Exception:
                # If we can't even get the peer_id, just return False
                return False

            self._handle_dead_peer(peer_id)
            return False

    Pubsub.write_msg = safe_write_msg


def patch_maybe_delete_peer_record():
    """
    Patch fixes an issue in PeerStore.maybe_delete_peer_record where it crashes a peer with StreamReset when another peer is disconnected.
    """

    def safe_maybe_delete_peer_record(self: PeerStore, peer_id: ID) -> bool:
        if peer_id in self.peer_record_map:
            try:
                if not self.addrs(peer_id):
                    self.peer_record_map.pop(peer_id, None)
            except Exception as e:
                logger.error(f"Failed to maybe delete peer record for {peer_id}: {e}")

    PeerStore.maybe_delete_peer_record = safe_maybe_delete_peer_record


def patch__update_peerstore_from_identify():
    async def _safe_update_peerstore_from_identify(peerstore: IPeerStore, peer_id: ID, identify_msg) -> None:
        """
        Update the peerstore with information from an identify message.

        This function handles partial updates, where only some fields may be present
        in the identify message.

        Security: Signed peer records are validated to ensure the peer ID in the
        record matches the sender's peer ID to prevent peer ID spoofing attacks.
        """
        # Update public key if present
        if identify_msg.HasField("public_key"):
            try:
                peerstore.add_protocols(peer_id, [])
                pubkey = deserialize_public_key(identify_msg.public_key)
                peerstore.add_pubkey(peer_id, pubkey)
            except Exception as e:
                logger.error("Error updating public key for peer %s: %s", peer_id, e)

        # Update listen addresses if present
        if identify_msg.listen_addrs:
            try:
                addrs = [Multiaddr(addr) for addr in identify_msg.listen_addrs]
                for addr in addrs:
                    peerstore.add_addr(peer_id, addr, 7200)  # 2 hours TTL
            except Exception as e:
                logger.error("Error updating listen addresses for peer %s: %s", peer_id, e)

        # Update protocols if present
        if identify_msg.protocols:
            try:
                peerstore.add_protocols(peer_id, identify_msg.protocols)
            except Exception as e:
                logger.error("Error updating protocols for peer %s: %s", peer_id, e)

        # Update from signed peer record if present
        if identify_msg.HasField("signedPeerRecord"):
            try:
                envelope, record = consume_envelope(identify_msg.signedPeerRecord, "libp2p-peer-record")
                # Cross-check peer-id consistency
                # Security: Reject signed peer records where the peer ID doesn't match
                # the sender's peer ID to prevent peer ID spoofing attacks
                if record.peer_id != peer_id:
                    logger.warning(
                        "SignedPeerRecord peer-id mismatch: record=%s, sender=%s. Ignoring.",
                        record.peer_id,
                        peer_id,
                    )
                    return  # Reject forged record - peer ID mismatch

                if not peerstore.consume_peer_record(envelope, 7200):
                    logger.error("Updating Certified-Addr-Book was unsuccessful for %s", peer_id)
            except Exception as e:
                logger.error("Error updating the certified addr book for peer %s: %s", peer_id, e)

        # Update observed address if present
        if identify_msg.HasField("observed_addr") and identify_msg.observed_addr:
            try:
                print("observed_addr", identify_msg.observed_addr)
                observed_addr = Multiaddr(identify_msg.observed_addr)
                peerstore.add_addr(peer_id, observed_addr, 7200)
            except Exception as e:
                logger.error("Error updating observed address for peer %s: %s", peer_id, e)

    identify_push._update_peerstore_from_identify = _safe_update_peerstore_from_identify


def apply_all_patches():
    """Apply all libp2p stability patches."""
    patch_get_in_topic_gossipsub_peers_from_minus()
    patch_write_msg()
    patch_maybe_delete_peer_record()
    patch__update_peerstore_from_identify()
