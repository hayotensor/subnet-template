from __future__ import annotations

from collections.abc import Sequence
import logging

from libp2p.crypto.keys import KeyPair
from libp2p.pubsub.pubsub import ValidatorFn
from libp2p.rcmgr.manager import ResourceManager
import trio

from examples.pubsub.heartbeat.config import HEARTBEAT_TOPIC
from examples.pubsub.heartbeat.publisher import HeartbeatPublisher
from examples.pubsub.heartbeat.receiver import HeartbeatReceiver
from examples.pubsub.heartbeat.validator import SyncHeartbeatMsgValidator
from examples.pubsub.peer_state.config import PEER_STATE_TOPIC
from examples.pubsub.peer_state.publisher import PeerRole, PeerStatePublisher, ServerState
from examples.pubsub.peer_state.receiver import PeerStateReceiver
from examples.pubsub.peer_state.validator import SyncPeerStateMsgValidator
from subnet.hypertensor.chain_functions import Hypertensor
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
from subnet.server.server_template import ApplicationBase, P2PNetworkContext, ServerBase
from subnet.telemetry.telemetry import Telemetry
from subnet.utils.db.database import RocksDB
from subnet.utils.logging_config import configure_logging
from subnet.utils.pos.proof_of_stake import ProofOfStake
from subnet.utils.pubsub.pubsub_validation import SyncPubsubTopicValidator

configure_logging()
logger = logging.getLogger("basic-server/1.0.0")

OFFLINE_GOSSIP_SETTLE_SECONDS = 3.0


class BasicPubsubApplication(ApplicationBase):
    """Basic subnet application that uses pubsub topics without a DAG."""

    def __init__(
        self,
        *,
        subnet_id: int,
        subnet_node_id: int,
        hypertensor: Hypertensor | LocalMockHypertensor,
        is_bootstrap: bool,
        enable_pubsub_validator: bool,
        enable_proof_of_stake: bool,
        telemetry: Telemetry | None,
        heartbeat_validator_log_level: int,
        gossip_receiver_log_level: int,
        publish_heartbeat_log_level: int,
        offline_gossip_settle_seconds: float,
    ) -> None:
        super().__init__()
        self.subnet_id = subnet_id
        self.subnet_node_id = subnet_node_id
        self.hypertensor = hypertensor
        self.is_bootstrap = is_bootstrap
        self.enable_pubsub_validator = enable_pubsub_validator
        self.proof_of_stake = (
            ProofOfStake(subnet_id=subnet_id, hypertensor=hypertensor, min_class=0)
            if enable_proof_of_stake
            else None
        )
        self.telemetry = telemetry
        self.heartbeat_validator_log_level = heartbeat_validator_log_level
        self.gossip_receiver_log_level = gossip_receiver_log_level
        self.publish_heartbeat_log_level = publish_heartbeat_log_level
        self.offline_gossip_settle_seconds = max(0.0, offline_gossip_settle_seconds)
        self.heartbeat_receiver: HeartbeatReceiver | None = None
        self.peer_state_receiver: PeerStateReceiver | None = None
        self.heartbeat_publisher: HeartbeatPublisher | None = None
        self.peer_state_publisher: PeerStatePublisher | None = None

    async def setup(self, context: P2PNetworkContext) -> None:
        if context.pubsub is None or context.gossipsub is None:
            raise RuntimeError("BasicPubsubApplication requires pubsub and gossipsub")

        if context.subnet_info_tracker is not None and not context.subnet_info_tracker.is_running:
            context.nursery.start_soon(context.subnet_info_tracker.run)

        if self.telemetry:
            context.nursery.start_soon(self.telemetry.run)

        if context.peer_multiaddr is not None:
            logger.info("Running peer on %s", context.peer_multiaddr)

    async def start_application(self, context: P2PNetworkContext) -> None:
        if context.pubsub is None:
            raise RuntimeError("BasicPubsubApplication requires pubsub")

        self.heartbeat_receiver = HeartbeatReceiver(
            pubsub=context.pubsub,
            termination_event=context.termination_event,
            topic=HEARTBEAT_TOPIC,
            topic_validator=self._heartbeat_validator(context),
            log_level=self.gossip_receiver_log_level,
        )
        self.peer_state_receiver = PeerStateReceiver(
            pubsub=context.pubsub,
            termination_event=context.termination_event,
            topic=PEER_STATE_TOPIC,
            topic_validator=self._peer_state_validator(context),
            log_level=self.gossip_receiver_log_level,
        )
        context.nursery.start_soon(self.heartbeat_receiver.run)
        context.nursery.start_soon(self.peer_state_receiver.run)

        if self.is_bootstrap:
            logger.info("Bootstrap node is receiving pubsub topics but skipping publishers")
            return

        self._validate_publisher_identity()
        self.heartbeat_publisher = HeartbeatPublisher(
            pubsub=context.pubsub,
            topic=HEARTBEAT_TOPIC,
            subnet_id=self.subnet_id,
            subnet_node_id=self.subnet_node_id,
            hypertensor=self.hypertensor,
            telemetry=self.telemetry,
            log_level=self.publish_heartbeat_log_level,
        )
        self.peer_state_publisher = PeerStatePublisher(
            pubsub=context.pubsub,
            topic=PEER_STATE_TOPIC,
            start_state=ServerState.JOINING,
            start_role=PeerRole.VALIDATOR,
            subnet_id=self.subnet_id,
            subnet_node_id=self.subnet_node_id,
            hypertensor=self.hypertensor,
            telemetry=self.telemetry,
            log_level=self.publish_heartbeat_log_level,
        )

        await self.peer_state_publisher.publish()
        self.peer_state_publisher.update_state(ServerState.ONLINE)
        context.nursery.start_soon(self.heartbeat_publisher.run)
        context.nursery.start_soon(self.peer_state_publisher.run)

    async def cleanup(self, context: P2PNetworkContext) -> None:
        if self.peer_state_publisher is None:
            logger.info("Basic pubsub application shutting down")
            return

        logger.info("Publishing final offline peer state before shutdown")
        self.peer_state_publisher.update_state(ServerState.OFFLINE)
        await self.peer_state_publisher.publish()
        if self.offline_gossip_settle_seconds > 0:
            await trio.sleep(self.offline_gossip_settle_seconds)
        logger.info("Basic pubsub application shutting down")

    def _heartbeat_validator(self, context: P2PNetworkContext) -> ValidatorFn | None:
        if not self.enable_pubsub_validator:
            return None

        if context.subnet_info_tracker is None:
            logger.warning("Heartbeat validator disabled because no SubnetInfoTracker is available")
            return None

        return SyncPubsubTopicValidator.from_predicate_class(
            SyncHeartbeatMsgValidator,
            context.host.get_id(),
            context.subnet_info_tracker,
            self.hypertensor,
            self.subnet_id,
            self.proof_of_stake,
            telemetry=self.telemetry,
            log_level=self.heartbeat_validator_log_level,
        ).validate

    def _peer_state_validator(self, context: P2PNetworkContext) -> ValidatorFn | None:
        if not self.enable_pubsub_validator:
            return None

        return SyncPubsubTopicValidator.from_predicate_class(
            SyncPeerStateMsgValidator,
            context.host.get_id(),
            self.proof_of_stake,
            telemetry=self.telemetry,
            log_level=self.gossip_receiver_log_level,
        ).validate

    def _validate_publisher_identity(self) -> None:
        if self.subnet_id <= 0:
            raise ValueError("Basic pubsub publishers require subnet_id greater than 0")
        if self.subnet_node_id <= 0:
            raise ValueError("Basic pubsub publishers require subnet_node_id greater than 0")


class Server(ServerBase):
    """Template-backed basic server that only runs the pubsub example logic."""

    def __init__(
        self,
        *,
        ip: str | None = None,
        port: int,
        peerstore_db_path: str | None = None,
        bootstrap_addrs: Sequence[str] | None = None,
        key_pair: KeyPair,
        db: RocksDB,
        subnet_id: int = 0,
        subnet_slot: int = 3,
        subnet_node_id: int = 0,
        hypertensor: Hypertensor | LocalMockHypertensor,
        is_bootstrap: bool = False,
        enable_pubsub_validator: bool = True,
        enable_consensus: bool = False,
        enable_proof_of_stake: bool = True,
        strict_maintain_connections: bool = True,
        enable_mDNS: bool = False,
        enable_upnp: bool = False,
        enable_autotls: bool = False,
        resource_manager: ResourceManager | None = None,
        psk: str | None = None,
        telemetry: Telemetry | None = None,
        heartbeat_validator_log_level: int = logging.DEBUG,
        gossip_receiver_log_level: int = logging.DEBUG,
        publish_heartbeat_log_level: int = logging.DEBUG,
        maintain_connections_log_level: int = logging.DEBUG,
        offline_gossip_settle_seconds: float = OFFLINE_GOSSIP_SETTLE_SECONDS,
        **kwargs: object,
    ) -> None:
        logger.info("Server starting subnet_id=%s", subnet_id)

        application = BasicPubsubApplication(
            subnet_id=subnet_id,
            subnet_node_id=subnet_node_id,
            hypertensor=hypertensor,
            is_bootstrap=is_bootstrap,
            enable_pubsub_validator=enable_pubsub_validator,
            enable_proof_of_stake=enable_proof_of_stake,
            telemetry=telemetry,
            heartbeat_validator_log_level=heartbeat_validator_log_level,
            gossip_receiver_log_level=gossip_receiver_log_level,
            publish_heartbeat_log_level=publish_heartbeat_log_level,
            offline_gossip_settle_seconds=offline_gossip_settle_seconds,
        )

        super().__init__(
            ip=ip or "0.0.0.0",
            port=port,
            application=application,
            key_pair=key_pair,
            bootstrap_addrs=bootstrap_addrs,
            use_available_interfaces=True,
            enable_pubsub=True,
            enable_random_walk=True,
            enable_mDNS=enable_mDNS,
            enable_upnp=enable_upnp,
            enable_autotls=enable_autotls,
            resource_manager=resource_manager,
            psk=psk,
            peerstore_db_path=peerstore_db_path,
            max_connections_per_peer=6,
            enable_proof_of_stake=enable_proof_of_stake,
            db=db,
            subnet_id=subnet_id,
            subnet_slot=subnet_slot,
            subnet_node_id=subnet_node_id,
            hypertensor=hypertensor,
            is_bootstrap=is_bootstrap,
            enable_subnet_info_tracker=enable_pubsub_validator,
            enable_consensus=enable_consensus,
            log_random_walk=True,
            random_walk_log_interval=30,
            enable_connection_maintenance=True,
            strict_maintain_connections=strict_maintain_connections,
            telemetry=telemetry,
            maintain_connections_log_level=maintain_connections_log_level,
            **kwargs,
        )
