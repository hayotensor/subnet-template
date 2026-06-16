"""CLI command to run a blank libp2p subnet server template node."""

import argparse
import logging
import random
import secrets
import sys

from libp2p.crypto.ed25519 import create_new_key_pair
import trio

from subnet.server.server_template import ApplicationBase, ServerBase
from subnet.utils.crypto.store_key import get_key_pair
from subnet.utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

RUN_NODE_EXAMPLES = r"""
Examples:
# Run locally with no RPC connection

# Start bootnode (or start bootnode through `run_bootnode`)

# 12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF

python -m subnet.cli.run_node \
--private_key_path bootnode.key \
--port 38960 \
--subnet_id 1 \
--no_blockchain_rpc \
--is_bootstrap \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest


# Connect to bootnode

# 12D3KooWMwW1VqH7uWtUc5UGoyMJp1dG26Nkosc6RkRJ7RNiW6Cb

python -m subnet.cli.run_node \
--private_key_path alith.key \
--port 38961 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 1 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

# 12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV

python -m subnet.cli.run_node \
--private_key_path baltathar.key \
--ip 127.0.0.1 \
--port 38962 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 2 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

# 12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt

python -m subnet.cli.run_node \
--private_key_path charleth.key \
--port 38963 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 3 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

# 12D3KooWD1BgwEJGUXz3DsKVXGFq3VcmHRjeX56NKpyEa1QAP6uV

python -m subnet.cli.run_node \
--private_key_path dorothy.key \
--port 38964 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 4 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

# 12D3KooWMGKEpzz3EWGU2ayhwFriRh23QnQ479Ctfj8xSmDRirde

python -m subnet.cli.run_node \
--private_key_path ethan.key \
--port 38965 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 5 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

# 12D3KooWF963f4jiFX26xDKu7BrqtVYTx4Jk8rUQQUxwiJQjVFWH

python -m subnet.cli.run_node \
--private_key_path faith.key \
--port 38966 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 6 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

python -m subnet.cli.run_node \
--private_key_path george.key \
--port 38967 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 7 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

python -m subnet.cli.run_node \
--private_key_path harry.key \
--port 38968 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 8 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest

python -m subnet.cli.run_node \
--private_key_path ian.key \
--port 38969 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 9 \
--no_blockchain_rpc \
--maintain_connections_log_level 20 \
--telemetry_url ws://127.0.0.1:8080/ingest


# Run locally with local RPC connection

# Start bootnode (or start bootnode through `run_bootnode`)

- Register subnet
- Register subnet nodes

# Start nodes

python -m subnet.cli.run_node \
--private_key_path bootnode.key \
--port 38960 \
--subnet_id 1 \
--is_bootstrap \
--local_rpc

# Connect to bootnode

python -m subnet.cli.run_node \
--private_key_path alith.key \
--port 38961 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 128001 \
--subnet_node_id 1 \
--tensor_private_key 0x883189525adc71f940606d02671bd8b7dfe3b2f75e2a6ed1f5179ac794566b40 \
--local_rpc

python -m subnet.cli.run_node \
--private_key_path baltathar.key \
--port 38962 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 2 \
--tensor_private_key 0x6cbf451fc5850e75cd78055363725dcf8c80b3f1dfb9c29d131fece6dfb72490 \
--local_rpc

python -m subnet.cli.run_node \
--private_key_path charleth.key \
--port 38963 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF \
--subnet_id 1 \
--subnet_node_id 3 \
--tensor_private_key 0x51b7c50c1cd27de89a361210431e8f03a7ddda1a0c8c5ff4e4658ca81ac02720 \
--local_rpc
"""


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run a blank libp2p subnet template node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=RUN_NODE_EXAMPLES,
    )

    parser.add_argument(
        "--mode",
        default="server",
        help="[Deprecated] Accepted for compatibility; the blank template always runs as a server.",
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=None,
        help="IP to listen on. If omitted, the node listens on available interfaces.",
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
        help="Multiaddrs of bootstrap nodes. Provide a space-separated list of addresses.",
    )
    parser.add_argument(
        "--is_bootstrap",
        action="store_true",
        help="Accepted for compatibility; blank template nodes do not run subnet use-case logic.",
    )
    parser.add_argument(
        "--base_path",
        type=str,
        default=None,
        help="[Deprecated] Accepted for compatibility; the blank template does not open an app database.",
    )
    parser.add_argument(
        "--peerstore_db_path",
        type=str,
        default=None,
        help="[Currently not in use] Persistent peerstore is not implemented.",
    )

    # Legacy subnet-application flags. They remain accepted so existing scripts can
    # keep invoking run_node while the command runs only the reusable template.
    parser.add_argument("--disable_pubsub_validator", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--disable_consensus", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--disable_proof_of_stake", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--disable_strict_maintain_connections", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument(
        "--maintain_connections_log_level",
        type=int,
        default=logging.DEBUG,
        help="Log level for optional template connection maintenance. 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR",
    )

    # Host specific arguments.
    parser.add_argument("--enable_mDNS", action="store_true", help="Enable mDNS discovery")
    parser.add_argument("--enable_upnp", action="store_true", help="Enable UPnP discovery")
    parser.add_argument("--enable_autotls", action="store_true", help="Enable AutoTLS")
    parser.add_argument("--psk", type=str, default=None, help="Pre-shared key for libp2p")

    parser.add_argument(
        "--private_key_path",
        type=str,
        default=None,
        help="Path to the private key file for peer ID.",
    )
    parser.add_argument(
        "--subnet_id",
        type=int,
        default=0,
        help="[Deprecated] Accepted for compatibility; blank template nodes do not use a subnet ID.",
    )
    parser.add_argument(
        "--subnet_node_id",
        type=int,
        default=0,
        help="[Deprecated] Accepted for compatibility; blank template nodes do not use a subnet node ID.",
    )
    parser.add_argument("--no_blockchain_rpc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--insert_mock_overwatch_node", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local_rpc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tensor_private_key", type=str, required=False, help=argparse.SUPPRESS)
    parser.add_argument("--phrase", type=str, required=False, help=argparse.SUPPRESS)
    parser.add_argument("--telemetry_url", type=str, required=False, help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    return parser.parse_args()


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()

    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if args.mode != "server":
        logger.warning("Ignoring mode=%s; blank template run_node always runs a server", args.mode)
    if args.base_path is not None:
        logger.info("Ignoring --base_path; blank template run_node does not open an app database")
    if args.peerstore_db_path is not None:
        logger.warning("Ignoring --peerstore_db_path; persistent peerstore is not implemented")
    if args.telemetry_url is not None:
        logger.info("Ignoring --telemetry_url; blank template run_node has no telemetry-producing application")

    logger.info("Starting blank libp2p subnet template node...")

    port = args.port
    if port <= 0:
        port = random.randint(10000, 60000)
    logger.info("Using port: %s", port)

    if args.bootstrap:
        logger.info("Bootstrap peers: %s", args.bootstrap)
    else:
        logger.info("Running as standalone node (no bootstrap peers)")

    if args.private_key_path is None:
        key_pair = create_new_key_pair(secrets.token_bytes(32))
    else:
        key_pair = get_key_pair(args.private_key_path)

    try:
        server = ServerBase(
            ip=args.ip or "0.0.0.0",
            port=port,
            application=ApplicationBase(),
            key_pair=key_pair,
            bootstrap_addrs=args.bootstrap,
            use_available_interfaces=args.ip is None,
            enable_pubsub=False,
            enable_random_walk=True,
            enable_mDNS=args.enable_mDNS,
            enable_upnp=args.enable_upnp,
            enable_autotls=args.enable_autotls,
            psk=args.psk,
            peerstore_db_path=None,
            max_connections_per_peer=6,
            enable_proof_of_stake=False,
            subnet_id=args.subnet_id,
            subnet_node_id=args.subnet_node_id,
            is_bootstrap=args.is_bootstrap,
            enable_subnet_info_tracker=False,
            enable_consensus=False,
            log_random_walk=args.verbose,
            enable_connection_maintenance=False,
            strict_maintain_connections=False,
            maintain_connections_log_level=args.maintain_connections_log_level,
            log_level=logging.DEBUG if args.verbose else logging.INFO,
        )
        trio.run(server.run)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        sys.exit(0)
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
