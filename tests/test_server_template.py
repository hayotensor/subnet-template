from __future__ import annotations

import pytest
from libp2p.crypto.ed25519 import create_new_key_pair
import trio

from subnet.server.server_template import ConsensusRuntime, P2PNetworkContext, ServerBase


class FakeProviderStore:
    def __init__(self) -> None:
        self.provided: list[bytes] = []

    async def provide(self, key: bytes) -> bool:
        self.provided.append(key)
        return True


class FakeDHT:
    def __init__(self) -> None:
        self.provided: list[str] = []
        self.provider_store = FakeProviderStore()

    async def provide(self, key: str) -> bool:
        key.encode("utf-8")
        self.provided.append(key)
        return True


class FakeConsensus:
    def __init__(self) -> None:
        self.started = trio.Event()

    async def _main_loop(self) -> None:
        self.started.set()
        await trio.sleep_forever()


def _server(**kwargs) -> ServerBase:
    return ServerBase(
        port=0,
        key_pair=create_new_key_pair(bytes([1]) * 32),
        apply_libp2p_patches=False,
        **kwargs,
    )


def _network_context(nursery: trio.Nursery) -> P2PNetworkContext:
    return P2PNetworkContext(
        host=object(),  # type: ignore[arg-type]
        dht=object(),  # type: ignore[arg-type]
        nursery=nursery,
        termination_event=trio.Event(),
        listen_addrs=(),
    )


@pytest.mark.asyncio
async def test_server_template_provides_configured_dht_keys() -> None:
    server = _server(dht_provide_keys=["text-key", b"\x00content-key"])
    dht = FakeDHT()

    await server._provide_dht_keys(dht)  # type: ignore[arg-type]

    assert dht.provided == ["text-key"]
    assert dht.provider_store.provided == [b"\x00content-key"]


def test_server_template_treats_single_dht_provide_key_as_one_key() -> None:
    assert _server(dht_provide_keys="content-key").dht_provide_keys == ("content-key",)
    assert _server(dht_provide_keys=b"content-key").dht_provide_keys == (b"content-key",)


@pytest.mark.trio
async def test_server_template_starts_consensus_from_custom_factory() -> None:
    db = object()
    hypertensor = object()
    subnet_info_tracker = object()
    consensus = FakeConsensus()
    runtime_seen: ConsensusRuntime | None = None

    def build_consensus(runtime: ConsensusRuntime) -> FakeConsensus:
        nonlocal runtime_seen
        runtime_seen = runtime
        return consensus

    server = _server(
        enable_consensus=True,
        consensus_factory=build_consensus,
        db=db,
        hypertensor=hypertensor,
        subnet_id=123,
        subnet_node_id=456,
    )
    server.subnet_info_tracker = subnet_info_tracker  # type: ignore[assignment]

    async with trio.open_nursery() as nursery:
        context = _network_context(nursery)
        server._start_consensus(context)
        with trio.fail_after(1):
            await consensus.started.wait()
        nursery.cancel_scope.cancel()

    assert server.consensus is consensus
    assert runtime_seen is not None
    assert runtime_seen.db is db
    assert runtime_seen.hypertensor is hypertensor
    assert runtime_seen.subnet_id == 123
    assert runtime_seen.subnet_node_id == 456
    assert runtime_seen.subnet_info_tracker is subnet_info_tracker
    assert runtime_seen.context is context


@pytest.mark.trio
@pytest.mark.parametrize(
    "server_kwargs",
    [
        {"enable_consensus": False},
        {"enable_consensus": True, "is_bootstrap": True},
    ],
)
async def test_server_template_does_not_call_consensus_factory_when_consensus_is_skipped(
    server_kwargs: dict[str, object],
) -> None:
    calls = 0

    def build_consensus(runtime: ConsensusRuntime) -> FakeConsensus:
        nonlocal calls
        calls += 1
        raise AssertionError("consensus factory should not be called")

    server = _server(
        consensus_factory=build_consensus,
        db=object(),
        hypertensor=object(),
        **server_kwargs,
    )

    async with trio.open_nursery() as nursery:
        server._start_consensus(_network_context(nursery))
        nursery.cancel_scope.cancel()

    assert calls == 0
