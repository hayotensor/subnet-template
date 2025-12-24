"""CLI command to run a libp2p subnet server node."""

import argparse
import logging
import sys

import trio

from subnet.server.server_v2 import Server
import random
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
from libp2p.crypto.keys import KeyPair
from libp2p.peer.pb import crypto_pb2
from libp2p.crypto.ed25519 import Ed25519PrivateKey
from libp2p.peer.id import ID as PeerID

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run a libp2p subnet node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a standalone node
  python -m subnet.cli.run_node

  # Run a node connecting to bootstrap peers
  python -m subnet.cli.run_node --bootstrap /ip4/127.0.0.1/tcp/31330/p2p/QmBootstrapPeerID

  # Connect to multiple bootstrap peers
  python -m subnet.cli.run_node \\
    --bootstrap /ip4/192.168.1.100/tcp/31330/p2p/QmPeer1 \\
    --bootstrap /ip4/192.168.1.101/tcp/31330/p2p/QmPeer2

  # Run a node with an identity file
  python -m subnet.cli.run_node --identity_path alith-ed25519.key --port 38960 --bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
  python -m subnet.cli.run_node --identity_path baltathar-ed25519.key --port 38961 --bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
  python -m subnet.cli.run_node --identity_path charleth-ed25519.key --port 38962 --bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
        """,
    )

    parser.add_argument(
        "--mode",
        default="server",
        help="Run as a server or client node",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 for random)",
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help=(
            "Multiaddrs of bootstrap nodes. "
            "Provide a space-separated list of addresses. "
            "This is required for client mode."
        ),
    )

    parser.add_argument(
        "--identity_path", type=str, default=None, help="Path to the identity file. "
    )

    parser.add_argument(
        "--subnet_id", type=int, default=1, help="Subnet ID this node belongs to. "
    )

    parser.add_argument(
        "--subnet_node_id",
        type=int,
        default=1,
        help="Subnet node ID this node belongs to. ",
    )

    # add option to use verbose logging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Log startup information
    logger.info("Starting libp2p subnet server node...")

    port = args.port
    if port <= 0:
        port = random.randint(10000, 60000)
    logger.debug(f"Using port: {port}")

    if args.bootstrap:
        logger.info(f"Bootstrap peers: {args.bootstrap}")
    else:
        logger.info("Running as standalone node (no bootstrap peers)")

    # Create and run the server
    try:
        with open(f"{args.identity_path}", "rb") as f:
            data = f.read()
        private_key = crypto_pb2.PrivateKey.FromString(data)
        ed25519_private_key = Ed25519PrivateKey.from_bytes(private_key.Data)
        public_key = ed25519_private_key.get_public_key()
        key_pair = KeyPair(ed25519_private_key, public_key)

        hypertensor = LocalMockHypertensor(
            subnet_id=args.subnet_id,
            peer_id=PeerID.from_pubkey(key_pair.public_key),
            subnet_node_id=args.subnet_node_id,
            coldkey="",
            hotkey="",
            bootnode_peer_id="",
            client_peer_id="",
            reset_db=True if not args.bootstrap else False,
        )

        server = Server(
            port=port,
            bootstrap_addrs=args.bootstrap,
            key_pair=key_pair,
            subnet_id=args.subnet_id,
            subnet_node_id=args.subnet_node_id,
            hypertensor=hypertensor,
        )
        trio.run(server.run)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
