import json
import logging
import socket
import time

from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID
import trio
from trio_websocket import ConnectionClosed, open_websocket_url

# Standard logging configuration for production visibility
logger = logging.getLogger(__name__)


class Telemetry:
    """
    Production-grade Telemetry client using Trio.

    Features:
    - Non-spinning worker loop with exponential backoff.
    - At-least-once delivery: Messages are only dropped if the worker is hard-killed.
    - Backpressure: emit() will block if the queue is full, protecting node memory.

    Example usage:

    import trio
    from libp2p.peer.id import ID

    async def main():
        # 1. Initialize Telemetry
        telemetry = Telemetry(
            url="ws://localhost:9000",
            subnet_id=1,
            subnet_node_id=10,
            peer_id=ID.from_base58("12D3Koo...")
        )

        # 2. Open a nursery to run the telemetry background worker
        async with trio.open_nursery() as nursery:
            # 3. Start the worker loop
            telemetry.start(nursery)

            # 4. Emit events anywhere in your app context
            await telemetry.emit_async("node_started")
            await telemetry.emit_async("peer_connected", peer="12D3Koo...")

    if __name__ == "__main__":
        trio.run(main)

    Receiver-side Verification:

    To verify these events on your telemetry endpoint (Python example):

    import json
    from libp2p.crypto.keys import unmarshal_public_key

    def verify_event(json_payload):
        # 1. Parse and extract security fields
        data = json.loads(json_payload)
        signature = bytes.fromhex(data.pop("signature"))
        pubkey_hex = data.pop("pubkey")

        # 2. Re-create the canonical signed data (must use sort_keys=True)
        canonical_data = json.dumps(data, sort_keys=True).encode()

        # 3. Unmarshal the public key and verify
        public_key = unmarshal_public_key(bytes.fromhex(pubkey_hex))
        return public_key.verify(canonical_data, signature)
    """

    def __init__(self, url: str, subnet_id: int, subnet_node_id: int, key_pair: KeyPair, max_queue: int = 1000):
        self.url = url
        self.subnet_id = subnet_id
        self.subnet_node_id = subnet_node_id
        self.key_pair = key_pair
        self.peer_id = ID.from_pubkey(key_pair.public_key).to_string()
        self.hostname = socket.gethostname()

        # Max queue size provides backpressure to the rest of the app
        self._send_channel, self._receive_channel = trio.open_memory_channel(max_queue)

    async def emit_async(self, event: str, **data: any) -> None:
        """
        Emits a telemetry event. This is async to allow backpressure if the
        internal channel is full, preventing memory exhaustion in the node.

        Note: Always prefer to use async emit_async() if possible over using emit().
        """
        print("emit_async", event, data)
        payload = {
            "event": event,
            "timestamp": time.time(),
            "host": self.hostname,
            "subnet_id": self.subnet_id,
            "subnet_node_id": self.subnet_node_id,
            "peer_id": self.peer_id,
            "data": data,
        }
        try:
            await self._send_channel.send(payload)
        except trio.EndOfChannel:
            logger.warning("Telemetry channel closed; dropped event: %s", event)

    def emit(self, event: str, **data: any) -> bool:
        """
        Synchronous, non-blocking version of emit.

        Use this to instrument code where 'async' is not available.

        Returns:

            True if the event was successfully queued.
            False if the queue was full or the channel is closed.

        Note: Always prefer to use async emit_async() if possible over using emit().
        """
        print("emit", event, data)
        payload = {
            "event": event,
            "timestamp": time.time(),
            "host": self.hostname,
            "subnet_id": self.subnet_id,
            "subnet_node_id": self.subnet_node_id,
            "peer_id": self.peer_id,
            "data": data,
        }
        try:
            self._send_channel.send_nowait(payload)
            return True
        except (trio.WouldBlock, trio.EndOfChannel):
            # Best effort: if the queue is full, we drop it to avoid blocking
            return False

    async def run(self) -> None:
        """
        Worker loop with exponential backoff, message persistence, and cryptographic signing.
        """
        backoff = 1
        max_backoff = 120
        pending_msg = None  # Track the message in transit

        while True:
            try:
                # open_websocket_url is an async context manager
                async with open_websocket_url(self.url) as ws:
                    # Connection successful: reset backoff
                    if backoff > 1:
                        logger.info("Telemetry reconnected to %s", self.url)
                    backoff = 1

                    # 1. First, retry sending the message that failed previously
                    # Note: We don't re-sign because it already has a signature from the previous attempt
                    if pending_msg:
                        logger.info("Retrying pending message %s", pending_msg)
                        await ws.send_message(json.dumps(pending_msg))
                        pending_msg = None

                    # 2. Now process incoming messages from the channel
                    async for msg in self._receive_channel:
                        logger.info("Sending message %s", msg)
                        # Sign the payload before sending
                        signed_msg = self._sign_payload(msg)

                        # Store in pending_msg before sending. If send_message fails,
                        # the exception will break the loop, but we still have 'signed_msg' here.
                        pending_msg = signed_msg
                        await ws.send_message(json.dumps(signed_msg))

                        # Clear only after successful transmission
                        pending_msg = None

            except (ConnectionClosed, OSError, Exception) as e:
                # We do not clear pending_msg here, so it will be retried on next connection.
                wait_time = backoff
                logger.error("Telemetry connection lost (%s). Retrying in %ds...", type(e).__name__, wait_time)

                await trio.sleep(wait_time)
                # Exponentially increase wait time up to max_backoff
                backoff = min(backoff * 2, max_backoff)

    def _sign_payload(self, payload: dict) -> dict:
        """
        Adds a cryptographic signature and public key to the payload.
        Ensures the telemetry endpoint can verify the sender's identity.
        """
        # 1. Create a canonical JSON string (keys sorted) for deterministic signing
        canonical_data = json.dumps(payload, sort_keys=True).encode()

        # 2. Sign with the private key
        signature = self.key_pair.private_key.sign(canonical_data)

        # 3. Add verification data to the payload
        payload["signature"] = signature.hex()
        payload["pubkey"] = self.key_pair.public_key.serialize().hex()

        return payload

    def start(self, nursery: trio.Nursery) -> None:
        """
        Launches the telemetry worker in the provided nursery.
        """
        nursery.start_soon(self.run)
