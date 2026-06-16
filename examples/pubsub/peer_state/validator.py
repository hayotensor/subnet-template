from enum import Enum
import logging

from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import ID
from pydantic import ValidationError

from subnet.telemetry.telemetry import Telemetry
from subnet.utils.pos.proof_of_stake import ProofOfStake

try:
    from .publisher import PeerStateData
except ImportError:  # Allows running this file directly from the example dir.
    from publisher import PeerStateData

logger = logging.getLogger("util.pubsub_validation")


class ValidationFailReason(Enum):
    PROOF_OF_STAKE_FAILURE = "proof_of_stake_failure"
    INVALID_DATA = "invalid_data"


class AsyncPeerStateMsgValidator:
    """
    Predicate for peer-state pubsub messages.

    This intentionally stays lightweight: it validates the payload with
    ``PeerStateData`` and optionally verifies proof of stake for the origin peer.
    """

    def __init__(
        self,
        my_peer_id: ID,
        proof_of_stake: ProofOfStake | None = None,
        telemetry: Telemetry | None = None,
        log_level: int = logging.DEBUG,
    ) -> None:
        self.my_peer_id = my_peer_id
        self.proof_of_stake = proof_of_stake
        self.telemetry = telemetry
        self.log_level = log_level

    async def __call__(self, forwarder_peer_id: ID, msg: rpc_pb2.Message) -> bool:
        try:
            from_peer_id = ID(msg.from_id)
            if from_peer_id.__eq__(self.my_peer_id):
                return True

            peer_state_data = self._decode_peer_state(forwarder_peer_id, from_peer_id, msg)
            if peer_state_data is None:
                await _async_validation_fail(
                    forwarder_peer_id,
                    from_peer_id,
                    None,
                    ValidationFailReason.INVALID_DATA,
                    self.telemetry,
                )
                return False

            logger.log(
                self.log_level,
                "AsyncPeerStateMsgValidator validate %s, PeerStateData %s",
                from_peer_id,
                peer_state_data,
            )

            if self.proof_of_stake is not None:
                pos = self.proof_of_stake.proof_of_stake(from_peer_id)
                if not pos:
                    await _async_validation_fail(
                        forwarder_peer_id,
                        from_peer_id,
                        peer_state_data,
                        ValidationFailReason.PROOF_OF_STAKE_FAILURE,
                        self.telemetry,
                    )
                    return False

            return True
        except Exception as e:
            logger.warning("Peer-state validation failed: %s", e, exc_info=True)
            return False

    @staticmethod
    def _decode_peer_state(
        forwarder_peer_id: ID,
        from_peer_id: ID,
        msg: rpc_pb2.Message,
    ) -> PeerStateData | None:
        try:
            return PeerStateData.from_json(msg.data.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, AssertionError, ValueError) as e:
            logger.warning(
                "PeerStateData validation failed, forwarder_peer_id %s, from_peer_id %s: %s",
                forwarder_peer_id,
                from_peer_id,
                e,
            )
            return None


class SyncPeerStateMsgValidator:
    """
    Synchronous predicate for peer-state pubsub messages.

    Use this with ``SyncPubsubTopicValidator`` when the pubsub topic validator
    is registered as a sync validator.
    """

    def __init__(
        self,
        my_peer_id: ID,
        proof_of_stake: ProofOfStake | None = None,
        telemetry: Telemetry | None = None,
        log_level: int = logging.DEBUG,
    ) -> None:
        self.my_peer_id = my_peer_id
        self.proof_of_stake = proof_of_stake
        self.telemetry = telemetry
        self.log_level = log_level

    def __call__(self, forwarder_peer_id: ID, msg: rpc_pb2.Message) -> bool:
        try:
            from_peer_id = ID(msg.from_id)
            if from_peer_id.__eq__(self.my_peer_id):
                return True

            peer_state_data = self._decode_peer_state(forwarder_peer_id, from_peer_id, msg)
            if peer_state_data is None:
                _validation_fail(
                    forwarder_peer_id,
                    from_peer_id,
                    None,
                    ValidationFailReason.INVALID_DATA,
                    self.telemetry,
                )
                return False

            logger.log(
                self.log_level,
                "SyncPeerStateMsgValidator validate %s, PeerStateData %s",
                from_peer_id,
                peer_state_data,
            )

            if self.proof_of_stake is not None:
                pos = self.proof_of_stake.proof_of_stake(from_peer_id)
                if not pos:
                    _validation_fail(
                        forwarder_peer_id,
                        from_peer_id,
                        peer_state_data,
                        ValidationFailReason.PROOF_OF_STAKE_FAILURE,
                        self.telemetry,
                    )
                    return False

            return True
        except Exception as e:
            logger.exception("Peer-state validation failed: %s", e)
            return False

    @staticmethod
    def _decode_peer_state(
        forwarder_peer_id: ID,
        from_peer_id: ID,
        msg: rpc_pb2.Message,
    ) -> PeerStateData | None:
        try:
            return PeerStateData.from_json(msg.data.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, AssertionError, ValueError) as e:
            logger.warning(
                "PeerStateData validation failed, forwarder_peer_id %s, from_peer_id %s: %s",
                forwarder_peer_id,
                from_peer_id,
                e,
            )
            return None


def _validation_fail(
    forwarder_peer_id: ID,
    from_peer_id: ID,
    peer_state_data: PeerStateData | None,
    reason: ValidationFailReason,
    telemetry: Telemetry | None = None,
) -> bool:
    logger.warning(
        "Peer-state validation failed, forwarder_peer_id %s, from_peer_id %s, peer_state %s, reason: %s",
        forwarder_peer_id,
        from_peer_id,
        peer_state_data,
        reason.value,
    )

    if telemetry:
        telemetry.emit(
            "peer_state_validation_failed",
            from_peer_id=from_peer_id.to_string(),
            reason=reason.value,
            data=peer_state_data,
        )

    return False


async def _async_validation_fail(
    forwarder_peer_id: ID,
    from_peer_id: ID,
    peer_state_data: PeerStateData | None,
    reason: ValidationFailReason,
    telemetry: Telemetry | None = None,
) -> bool:
    logger.warning(
        "Peer-state validation failed, forwarder_peer_id %s, from_peer_id %s, peer_state %s, reason: %s",
        forwarder_peer_id,
        from_peer_id,
        peer_state_data,
        reason.value,
    )

    if telemetry:
        await telemetry.emit_async(
            "peer_state_validation_failed",
            peer_id=from_peer_id.to_string(),
            reason=reason.value,
            data=peer_state_data,
        )

    return False
