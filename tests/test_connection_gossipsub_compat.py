import logging
import time

from libp2p.peer.id import ID
from libp2p.pubsub.gossipsub import GossipSub

from subnet.config import GOSSIPSUB_PROTOCOL_ID
from subnet.utils.connections.connection import (
    find_abusive_gossipsub_peers,
    log_gossipsub_peer_scores,
)


def _peer(seed: bytes) -> ID:
    return ID(seed)


def _gossipsub() -> GossipSub:
    return GossipSub(
        protocols=[GOSSIPSUB_PROTOCOL_ID],
        degree=7,
        degree_low=5,
        degree_high=10,
        heartbeat_interval=2,
    )


def test_find_abusive_gossipsub_peers_supports_pylibp2p_060_scorer() -> None:
    peer = _peer(b"peer-with-behavior-penalty")
    gossipsub = _gossipsub()
    scorer = gossipsub.scorer
    assert scorer is not None
    assert not hasattr(scorer, "graft_flood_penalties")

    gossipsub.peer_protocol[peer] = GOSSIPSUB_PROTOCOL_ID
    gossipsub.mesh["heartbeat"] = {peer}
    scorer.behavior_penalty[peer] = 60.0

    abusive_peers = find_abusive_gossipsub_peers(gossipsub, None)

    assert peer in abusive_peers
    assert any(reason.startswith("behavior_penalty=60.0") for reason in abusive_peers[peer])


def test_find_abusive_gossipsub_peers_uses_optional_control_penalty_maps() -> None:
    peer = _peer(b"peer-with-control-penalty")
    gossipsub = _gossipsub()
    scorer = gossipsub.scorer
    assert scorer is not None

    gossipsub.peer_protocol[peer] = GOSSIPSUB_PROTOCOL_ID
    setattr(scorer, "graft_flood_penalties", {peer: 30.0})

    abusive_peers = find_abusive_gossipsub_peers(gossipsub, None)

    assert peer in abusive_peers
    assert any(reason.startswith("control_penalty=30.0") for reason in abusive_peers[peer])


def test_log_gossipsub_peer_scores_supports_pylibp2p_060_router(caplog) -> None:
    peer = _peer(b"peer-for-score-logging")
    gossipsub = _gossipsub()
    gossipsub.peer_protocol[peer] = GOSSIPSUB_PROTOCOL_ID
    gossipsub.mesh["heartbeat"] = {peer}
    gossipsub.message_rate_limits[peer]["heartbeat"].append(time.time())

    with caplog.at_level(logging.DEBUG, logger="subnet.utils.connection"):
        log_gossipsub_peer_scores(gossipsub, None, logging.DEBUG)

    assert "Failed to log GossipSub peer scores" not in caplog.text
    assert "GossipSub peer scores:" in caplog.text
