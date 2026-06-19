import pytest
from libp2p.peer.id import ID
from libp2p.security.exceptions import HandshakeFailure

from subnet.utils.pos.exceptions import InvalidProofOfStake
from subnet.utils.pos.pos_transport import POSTransport


class FakeSecureConn:
    def __init__(self, remote_peer: ID) -> None:
        self.remote_peer = remote_peer


class FakeSecureTransport:
    def __init__(self, remote_peer: ID) -> None:
        self.remote_peer = remote_peer
        self.inbound_calls = 0
        self.outbound_calls = 0

    async def secure_inbound(self, _conn) -> FakeSecureConn:
        self.inbound_calls += 1
        return FakeSecureConn(self.remote_peer)

    async def secure_outbound(self, _conn, _peer_id: ID) -> FakeSecureConn:
        self.outbound_calls += 1
        return FakeSecureConn(self.remote_peer)


class ErroringProofOfStake:
    def __init__(self) -> None:
        self.calls: list[ID] = []
        self.failed_peer_ids: list[ID] = []

    def proof_of_stake(self, peer_id: ID) -> bool:
        self.calls.append(peer_id)
        raise RuntimeError("chain rpc unavailable")

    def update_peer_id_fail(self, peer_id: ID) -> None:
        self.failed_peer_ids.append(peer_id)


@pytest.mark.asyncio
async def test_pos_transport_rejects_inbound_peer_when_pos_check_errors() -> None:
    remote_peer = ID(b"peer-with-pos-error")
    transport = FakeSecureTransport(remote_peer)
    pos = ErroringProofOfStake()
    wrapped = POSTransport(transport=transport, pos=pos)

    with pytest.raises(InvalidProofOfStake) as exc_info:
        await wrapped.secure_inbound(object())

    assert isinstance(exc_info.value, HandshakeFailure)
    assert transport.inbound_calls == 1
    assert pos.calls == [remote_peer]
    assert pos.failed_peer_ids == [remote_peer]


@pytest.mark.asyncio
async def test_pos_transport_rejects_outbound_peer_when_pos_check_errors() -> None:
    remote_peer = ID(b"peer-with-pos-error")
    transport = FakeSecureTransport(remote_peer)
    pos = ErroringProofOfStake()
    wrapped = POSTransport(transport=transport, pos=pos)

    with pytest.raises(InvalidProofOfStake) as exc_info:
        await wrapped.secure_outbound(object(), remote_peer)

    assert isinstance(exc_info.value, HandshakeFailure)
    assert transport.outbound_calls == 1
    assert pos.calls == [remote_peer]
    assert pos.failed_peer_ids == [remote_peer]
