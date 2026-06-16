import logging
from typing import Awaitable, Callable

from libp2p.pubsub.pb import (
    rpc_pb2,
)
from libp2p.pubsub.pubsub import ID

logger = logging.getLogger("util.pubsub_validation")


class AsyncPubsubTopicValidator:
    """
    Validator for Puspub heartbeat messages.

    Create a class that implements __call__ to validate messages.

    Example:
        pubsub = Pubsub(...)
        pubsub.set_topic_validator(
            HEARTBEAT_TOPIC,
            AsyncPubsubTopicValidator.from_predicate_class(
                AsyncHeartbeatMsgValidator,
                host.get_id(),
                subnet_info_tracker,
                self.hypertensor,
                self.subnet_id,
                proof_of_stake,
            ).validate,
            is_async_validator=True,
        )

    """

    def __init__(self, fn: Callable[[ID, rpc_pb2.Message], Awaitable[bool]]):
        self.fn = fn

    @classmethod
    def from_predicate_class(cls, predicate_cls: type, *args, **kwargs) -> "AsyncPubsubTopicValidator":
        """
        Example:
            AsyncPubsubTopicValidator.from_predicate_class(
                host.get_id(),
                AsyncHeartbeatMsgValidator,
                subnet_info_tracker,
                hypertensor,
                subnet_id,
                proof_of_stake,
            )

        """
        predicate = predicate_cls(*args, **kwargs)
        return cls(predicate)

    async def validate(self, peer_id: ID, msg: rpc_pb2.Message) -> bool:
        return await self.fn(peer_id, msg)


class SyncPubsubTopicValidator:
    """
    Validator for Puspub heartbeat messages.

    Create a class that implements __call__ to validate messages.

    Example:
        pubsub = Pubsub(...)
        pubsub.set_topic_validator(
            HEARTBEAT_TOPIC,
            SyncPubsubTopicValidator.from_predicate_class(
                AsyncHeartbeatMsgValidator,
                host.get_id(),
                subnet_info_tracker,
                self.hypertensor,
                self.subnet_id,
                proof_of_stake,
            ).validate,
            is_async_validator=True,
        )

    """

    def __init__(self, fn: Callable[[ID, rpc_pb2.Message], bool]):
        self.fn = fn

    @classmethod
    def from_predicate_class(cls, predicate_cls: type, *args, **kwargs) -> "SyncPubsubTopicValidator":
        """
        Example:
            SyncPubsubTopicValidator.from_predicate_class(
                host.get_id(),
                SyncHeartbeatMsgValidator,
                subnet_info_tracker,
                hypertensor,
                subnet_id,
                proof_of_stake,
            )

        """
        predicate = predicate_cls(*args, **kwargs)
        return cls(predicate)

    def validate(self, peer_id: ID, msg: rpc_pb2.Message) -> bool:
        return self.fn(peer_id, msg)
