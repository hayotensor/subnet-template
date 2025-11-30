import asyncio
import multiprocessing as mp
from dataclasses import asdict
from typing import List

from libp2p.kad_dht import KadDHT
from libp2p.peer.id import ID as PeerID
from subnet.consensus.utils import (
    compare_consensus_data,
    did_node_attest,
    is_validator_or_attestor,
)
from subnet.hypertensor.chain_data import SubnetNodeConsensusData
from subnet.hypertensor.chain_functions import Hypertensor, SubnetNodeClass
from subnet.hypertensor.config import BLOCK_SECS
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
import trio
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("consensus/1.0.0")


class Consensus(mp.Process):
    def __init__(
        self,
        dht: KadDHT,
        subnet_id: int,
        subnet_node_id: int,
        hypertensor: Hypertensor,
        skip_activate_subnet: bool = False,
        start: bool = True,
    ):
        super().__init__()
        self.dht = dht
        self.peer_id = self.dht.peer_id
        self.subnet_id = subnet_id
        self.subnet_node_id = subnet_node_id
        self.hypertensor = hypertensor
        self.is_subnet_active: bool = False
        self.skip_activate_subnet = skip_activate_subnet
        self.slot: int | None = None  # subnet epoch slot, set in `run_activate_subnet`
        self._inner_pipe, self._outer_pipe = mp.Pipe(duplex=True)
        self.stop = mp.Event()

        if start:
            self.start()

    def run(self):
        try:
            try:
                trio.run(self._main_loop())
            except KeyboardInterrupt:
                self.logger.debug("Caught KeyboardInterrupt, shutting down")
        except Exception as e:
            self.logger.error(f"Consensus run exception: {e}", exc_info=True)

    async def _main_loop(self):
        if not await self.run_activate_subnet():
            return
        if not await self.run_is_node_validator():
            return
        await self.run_forever()

    def get_validator(self, epoch: int):
        validator = self.hypertensor.get_rewards_validator(self.subnet_id, epoch)
        return validator

    def get_scores(self, current_epoch: int) -> List[SubnetNodeConsensusData]:
        """
        Fill in a way to get scores on each node

        These scores must be deterministic - See docs
        """
        # Get all nodes
        # nodes = get_node_infos_sig(
        #     self.dht, uid="node", latest=True, record_validator=self.record_validator
        # )

        nodes = self.dht.get_value(key=b"node")

        node_peer_ids = {n.peer_id for n in nodes}

        # Get all included nodes
        if self.hypertensor is None:
            self.logger.warning("Hypertensor RPC node required to get node scores")
            return []

        # Get each subnet node ID that is included onchain AND in the subnet
        included_nodes = self.hypertensor.get_min_class_subnet_nodes_formatted(
            self.subnet_id, current_epoch, SubnetNodeClass.Included
        )
        subnet_node_ids = [
            n.subnet_node_id
            for n in included_nodes
            if PeerID.from_base58(n.peer_id) in node_peer_ids
        ]

        """
            {
                "subnet_node_id": int,
                "score": int
            }

            Is the expected format on-chain

            We use asdict() when submitting
        """
        consensus_score_list = [
            SubnetNodeConsensusData(subnet_node_id=node_id, score=int(1e18))
            for node_id in subnet_node_ids
        ]

        return consensus_score_list

    async def run_activate_subnet(self):
        """
        Verify subnet is active on-chain before starting consensus

        For initial coldkeys this will sleep until the enactment period, then proceed
        to check once per epoch after enactment starts if the owner activated the subnet
        """
        print("run_activate_subnet")
        # Useful if subnet is already active and for testing
        if self.skip_activate_subnet:
            self.logger.info(
                "Skipping subnet activation and attempting to start consensus"
            )
            return True

        last_epoch = None
        subnet_active = False
        max_errors = 3
        errors_count = 0
        while not self.stop.is_set():
            print("run_activate_subnet while not")
            if self.slot is None or self.slot == "None":  # noqa: E711
                try:
                    print("run_activate_subnet before slot =")
                    slot = self.hypertensor.get_subnet_slot(self.subnet_id)
                    print("run_activate_subnet after slot =", slot)
                    if slot == None or slot == "None":  # noqa: E711
                        print("run_activate_subnet slot None")
                        await asyncio.sleep(BLOCK_SECS)
                        print("run_activate_subnet slot sleep done")
                        continue
                    print("run_activate_subnet assigning self.slot =", slot)
                    self.slot = int(str(slot))
                    print("run_activate_subnet assigning self.slot complete =", slot)
                    print(f"Subnet running in slot {self.slot}")
                    self.logger.info(f"Subnet running in slot {self.slot}")
                except Exception as e:
                    # print(f"Consensus get_subnet_slot={e}")
                    self.logger.warning(f"Consensus get_subnet_slot={e}", exc_info=True)

            epoch_data = self.hypertensor.get_epoch_data()
            current_epoch = epoch_data.epoch

            if current_epoch != last_epoch:
                # offset_sleep = 0
                subnet_info = self.hypertensor.get_formatted_subnet_info(self.subnet_id)
                if subnet_info is None or subnet_info == None:  # noqa: E711
                    # None means the subnet is likely deactivated
                    if errors_count > max_errors:
                        self.logger.warning(
                            "Cannot find subnet ID: %s, shutting down", self.subnet_id
                        )
                        self.shutdown()
                        subnet_active = False
                        break
                    else:
                        self.logger.warning(
                            f"Cannot find subnet ID: {self.subnet_id}, trying {max_errors - errors_count} more times"
                        )
                        errors_count = errors_count + 1
                else:
                    if subnet_info.state == "Active":
                        self.logger.info(
                            f"Subnet ID {self.subnet_id} is active, starting consensus"
                        )
                        subnet_active = True
                        break

                last_epoch = current_epoch

            print("Waiting for subnet to be activated. Sleeping until next epoch")
            self.logger.info(
                "Waiting for subnet to be activated. Sleeping until next epoch"
            )
            await asyncio.sleep(max(0.0, epoch_data.seconds_remaining))

        print("run_activate_subnet subnet_active", subnet_active)
        return subnet_active

    async def run_is_node_validator(self):
        """
        Verify node is active on-chain before starting consensus

        Node must be classed as Idle on-chain to to start consensus

        Included nodes cannot be the elected validator or attest but must take part in consensus
        and be included in the consensus data to graduate to a Validator classed node
        """
        last_epoch = None
        while not self.stop.is_set():
            epoch_data = self.hypertensor.get_subnet_epoch_data(self.slot)
            current_epoch = epoch_data.epoch

            if current_epoch != last_epoch:
                nodes = self.hypertensor.get_min_class_subnet_nodes_formatted(
                    self.subnet_id, current_epoch, SubnetNodeClass.Idle
                )
                node_found = False
                for node in nodes:
                    if node.subnet_node_id == self.subnet_node_id:
                        node_found = True
                        break

                if not node_found:
                    print(
                        f"Subnet Node ID {self.subnet_node_id} is not Validator class on epoch {current_epoch}. Trying again next epoch"
                    )
                    self.logger.info(
                        "Subnet Node ID %s is not Validator class on epoch %s. Trying again next epoch",
                        self.subnet_node_id,
                        current_epoch,
                    )
                else:
                    print(
                        f"Subnet Node ID {self.subnet_node_id} is classified as a Validator class on epoch {current_epoch}. Starting consensus."
                    )
                    self.logger.info(
                        "Subnet Node ID %s is classified as a Validator class on epoch %s. Starting consensus.",
                        self.subnet_node_id,
                        current_epoch,
                    )
                    break

                last_epoch = current_epoch

            print(f"run_is_node_validator sleeping for {epoch_data.seconds_remaining}")
            await asyncio.sleep(epoch_data.seconds_remaining)

        return True

    async def run_forever(self):
        """
        Loop until a new epoch to found, then run consensus logic
        """
        self._async_stop_event = asyncio.Event()
        last_epoch = None
        started = False

        print("About to begin consensus")
        self.logger.info("About to begin consensus")

        while not self.stop.is_set() and not self._async_stop_event.is_set():
            try:
                epoch_data = self.hypertensor.get_subnet_epoch_data(self.slot)

                # Start on fresh epoch
                if started is False:
                    started = True
                    try:
                        print(
                            f"Starting consensus on next epoch in {epoch_data.seconds_remaining}s"
                        )
                        self.logger.info(
                            f"Starting consensus on next epoch in {epoch_data.seconds_remaining}s"
                        )
                        await asyncio.wait_for(
                            self._async_stop_event.wait(),
                            timeout=epoch_data.seconds_remaining,
                        )
                        break  # Stop event was set
                    except asyncio.TimeoutError:
                        continue  # Timeout reached, continue to next iteration
                else:
                    print("✅ Starting consensus")
                    self.logger.info("✅ Starting consensus")

                current_epoch = epoch_data.epoch

                if current_epoch != last_epoch:
                    """
                    Add validation logic before and/or after `await run_consensus(current_epoch)`

                    The logic here should be for qualifying nodes (proving work), generating scores, etc.
                    """
                    # Attest/Validate
                    await self.run_consensus(current_epoch)
                    last_epoch = current_epoch

                    # Get fresh epoch data after processing
                    epoch_data = self.hypertensor.get_subnet_epoch_data(self.slot)

                # Wait for either stop event or timeout based on remaining time
                try:
                    await asyncio.wait_for(
                        self._async_stop_event.wait(),
                        timeout=epoch_data.seconds_remaining,
                    )
                    break  # Stop event was set
                except asyncio.TimeoutError:
                    pass  # Timeout reached, continue to next iteration
            except Exception as e:
                # logger.warning(e, exc_info=True)
                await asyncio.sleep(BLOCK_SECS)

    async def run_consensus(self, current_epoch: int):
        """
        At the start of each epoch, we check if we are validator

        Scores are likely generated and rooted from the `run_forever` function, although, any use cases are possible

        We start by:
            - Getting scores
                - Can generate scores in real-time or get from the DHT database

        If elected on-chain validator:
            - Submit scores to Hypertensor

        If attestor (non-elected on-chain validator):
            - Retrieve validators score submission from Hypertensor
            - Compare to our own
            - Attest if 100% accuracy, else do nothing
        """
        print(f"[Consensus] epoch: {current_epoch}")
        self.logger.info(f"[Consensus] epoch: {current_epoch}")

        scores = self.get_scores(current_epoch - 1)

        if scores is None:
            return

        validator = None
        # Wait until validator is chosen
        while not self.stop.is_set():
            validator = self.get_validator(current_epoch)
            epoch_data = self.hypertensor.get_subnet_epoch_data(self.slot)
            _current_epoch = epoch_data.epoch
            if _current_epoch != current_epoch:
                validator = None
                break

            if validator is not None or validator != "None":
                break

            # Wait until next block to try again
            await asyncio.sleep(BLOCK_SECS)

        if validator is None or validator == None:  # noqa: E711
            return

        if validator == self.subnet_node_id:
            print(
                f"🎖️ Acting as elected validator for epoch {current_epoch} and proposing an attestation to the blockchain"
            )
            self.logger.info(
                f"🎖️ Acting as elected validator for epoch {current_epoch} and proposing an attestation to the blockchain"
            )

            # See if attestation proposal submitted
            consensus_data = self.hypertensor.get_consensus_data_formatted(
                self.subnet_id, current_epoch
            )
            if consensus_data is not None:  # noqa: E711
                print("Already submitted data, moving to next epoch")
                self.logger.info("Already submitted data, moving to next epoch")

                return

            if len(scores) == 0:
                """
                Add any logic here for when no scores are present.

                The blockchain allows the validator to submit an empty score. This can mean
                the mesh is in a broken state or not synced.

                If other peers also come up with the same "zero" scores, they can attest the validator
                and the validator will not accrue penalties or be slashed. The subnet itself will accrue
                penalties until it recovers (penalties decrease for every successful epoch).

                No scores are generated, likely subnet in broken state and all other nodes
                should be too, so we submit consensus with no scores.

                This will increase subnet penalties, but avoid validator penalties.

                Any successful epoch following will remove these penalties on the subnet
                """
                self.hypertensor.propose_attestation(
                    self.subnet_id, data=[asdict(s) for s in scores]
                )
            else:
                self.hypertensor.propose_attestation(
                    self.subnet_id, data=[asdict(s) for s in scores]
                )

        elif validator is not None:
            print(f"🗳️ Acting as attestor/voter for epoch {current_epoch}")
            self.logger.info(f"🗳️ Acting as attestor/voter for epoch {current_epoch}")

            consensus_data = None  # Fetch one time once not None
            _is_validator_or_attestor = False  # Check only once
            while not self.stop.is_set():
                # Check consensus data exists in case attest fails
                if consensus_data is None or consensus_data == None:  # noqa: E711
                    consensus_data = self.hypertensor.get_consensus_data_formatted(
                        self.subnet_id, current_epoch
                    )

                epoch_data = self.hypertensor.get_subnet_epoch_data(self.slot)
                _current_epoch = epoch_data.epoch

                # If next epoch or validator took too long, move onto next steps
                if (
                    _current_epoch != current_epoch
                    or epoch_data.percent_complete > 0.15
                ):
                    break

                if consensus_data is None or consensus_data == None:  # noqa: E711
                    await asyncio.sleep(BLOCK_SECS)
                    continue

                validator_data = consensus_data.data

                """
                Get all of the hosters inference outputs they stored to the DHT
                """

                if 1.0 == compare_consensus_data(
                    my_data=scores, validator_data=validator_data
                ):
                    # Check if we can attest
                    # This is important in case a node sets emergency validators
                    if not _is_validator_or_attestor:
                        _is_validator_or_attestor = is_validator_or_attestor(
                            self.hypertensor, self.subnet_id, self.subnet_node_id
                        )
                        # If False, break
                        # If True, check once
                        if not _is_validator_or_attestor:
                            print("Not attestor or validator")
                            self.logger.debug("Not attestor or validator")

                            break

                    # Check if we already attested
                    if did_node_attest(self.subnet_node_id, consensus_data):
                        print("Already attested, moving to next epoch")
                        self.logger.debug("Already attested, moving to next epoch")

                        break

                    # print(f"✅ Elected validator's data matches for epoch {current_epoch}, attesting their data")
                    self.logger.info(
                        f"✅ Elected validator's data matches for epoch {current_epoch}, attesting their data"
                    )

                    receipt = self.hypertensor.attest(self.subnet_id)
                    if isinstance(
                        self.hypertensor, LocalMockHypertensor
                    ):  # don't check receipt if using mock
                        return

                    if receipt.is_success:
                        break
                    else:
                        await asyncio.sleep(BLOCK_SECS)
                else:
                    print(
                        f"❌ Data doesn't match validator's for epoch {current_epoch}, moving forward with no attetation"
                    )
                    self.logger.info(
                        f"❌ Data doesn't match validator's for epoch {current_epoch}, moving forward with no attetation"
                    )

                    break

    def shutdown(self, timeout: float = 5.0):
        if not self.stop.is_set():
            self.stop.set()

        if self.is_alive():
            self.join(3)
            if self.is_alive():
                logger.warning(
                    "Consensus did not shut down within the grace period; terminating it the hard way"
                )
                self.terminate()
        else:
            logger.warning(
                "Consensus shutdown had no effect, the process is already dead"
            )
