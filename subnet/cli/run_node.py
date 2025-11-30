"""CLI command to run a libp2p subnet server node."""

import argparse
import logging
import sys

import trio

from subnet.server.server import Server
import random

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
        description="Run a libp2p subnet server node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a standalone node (no bootstrap peers)
  python -m subnet.cli.run_node

  # Run a node connecting to bootstrap peers
  python -m subnet.cli.run_node --bootstrap /ip4/127.0.0.1/tcp/31330/p2p/QmBootstrapPeerID

  # Connect to multiple bootstrap peers
  python -m subnet.cli.run_node \\
    --bootstrap /ip4/192.168.1.100/tcp/31330/p2p/QmPeer1 \\
    --bootstrap /ip4/192.168.1.101/tcp/31330/p2p/QmPeer2
        """,
    )

    parser.add_argument(
        "--bootstrap",
        "-b",
        action="append",
        dest="bootstrap_addrs",
        default=[],
        metavar="MULTIADDR",
        help="Bootstrap peer multiaddress (can be specified multiple times). "
        "Format: /ip4/<IP>/tcp/<PORT>/p2p/<PEER_ID>",
    )

    parser.add_argument(
        "--port",
        "-p",
        type=int,
        required=False,
        help="Port this server listens to. "
        "This is a simplified way to set the --host_maddrs and --announce_maddrs options (see below) "
        "that sets the port across all interfaces (IPv4, IPv6) and protocols (TCP, etc.) "
        "to the same number. Default: a random free port is chosen for each interface and protocol",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)",
    )

    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="%(prog)s 0.1.0",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()

    # Set logging level
    logging.getLogger().setLevel(args.log_level)

    # Log startup information
    logger.info("Starting libp2p subnet server node...")

    port = args.port
    if port <= 0:
        port = random.randint(10000, 60000)
    logger.debug(f"Using port: {port}")

    if args.bootstrap_addrs:
        logger.info(f"Bootstrap peers: {args.bootstrap_addrs}")
    else:
        logger.info("Running as standalone node (no bootstrap peers)")

    # Create and run the server
    try:
        server = Server(port=port, bootstrap_addrs=args.bootstrap_addrs)
        trio.run(server.run)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
