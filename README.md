# py-libp2p-subnet

A subnet template framework implementation.

⚠️ This is a work in progress and is not yet ready for production use.

## Installation

### From Source

Clone the repository and install:

```bash
git clone https://github.com/hayotensor/py-libp2p-subnet.git
cd py-libp2p-subnet
python -m venv .venv
source .venv/bin/activate
pip install .
touch .env
```

### Development Installation

For development, install with dev dependencies:

```bash
pip install -e ".[dev]"
```

```python
# Import your package
import subnet

# Add usage examples here
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=subnet --cov-report=html

# Run specific test file
pytest tests/test_example.py
```

### Running Locally

The the subnetwork locally with no blockchain integration for testing purposes.

#### Start Bootnode (Alith)

Start the bootnode that doesn't participate in consensus

```bash
python -m subnet.cli.run_node \
--private_key_path alith.key \
--port 38960 \
--subnet_id 1 \
--no_blockchain_rpc \
--is_bootstrap \
--no_blockchain_rpc
```

#### Start Peers (Nodes)

##### Start Node 1 (Baltathar)

```bash
python -m subnet.cli.run_node \
--private_key_path baltathar.key \
--port 38961 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 1 \
--no_blockchain_rpc
```

##### Start Node 2 (Charleth)

```bash
python -m subnet.cli.run_node \
--private_key_path charleth.key \
--port 38962 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 2 \
--no_blockchain_rpc
```

##### Start Node 3 (Dorothy)

```bash
python -m subnet.cli.run_node \
--private_key_path dorothy.key \
--port 38963 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 3 \
--no_blockchain_rpc
```

### Running Local RPC (Local BLockchain)

Start the blockchain (See [GitHub](https://github.com/hypertensor-blockchain/hypertensor-blockchain))

#### Register Subnet

Register with Alith as the owner

```bash
register_subnet \
--max_cost 100.00 \
--name subnet-1 \
--repo github.com/subnet-1 \
--description "artificial intelligence" \
--misc "cool subnet" \
--min_stake 100.00 \
--max_stake  1000.00 \
--delegate_stake_percentage 0.1 \
--initial_coldkey 0xf24FF3a9CF04c71Dbc94D0b566f7A27B94566cac 1 \
--initial_coldkey 0x3Cd0A705a2DC65e5b1E1205896BaA2be8A07c6e0 1 \
--initial_coldkey 0x798d4Ba9baf0064Ec19eB4F0a1a45785ae9D6DFc 1 \
--initial_coldkey 0x773539d4Ac0e786233D90A233654ccEE26a613D9 1 \
--key_types "Rsa" \
--bootnodes "p2p/127.0.0.1/tcp" \
--private_key "0x5fb92d6e98884f76de468fa3f6278f8807c48bebc13595d45af5bdc4da702133" \
--local_rpc
```

#### Register Nodes

##### Register Node ID 1 (Baltathar, baltathar.key)

We use alith.key as the bootnode of node ID to pass validation mechanisms like proof-of-stake and connection maintenance.

```bash
register_node \
--subnet_id 1 \
--hotkey 0xc30fE91DE91a3FA79E42Dfe7a01917d0D92D99D7 \
--peer_id 12D3KooWBqJu85tnb3WciU3LcXhCmTdkvMi4k1Zq3BshUPhVfTui \
--bootnode_peer_id 12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--bootnode /ip4/127.00.1/tcp/38960/p2p/12D3KooWBqJu85tnb3WciU3LcXhCmTdkvMi4k1Zq3BshUPhVfTui \
--client_peer_id 12D3KooWBqJu85tnb3WciU3LcXhCmTdkvMi4k1Zq3BshUPhVfTuk \
--delegate_reward_rate 0.125 \
--stake_to_be_added 200.00 \
--max_burn_amount 100.00 \
--private_key "0x8075991ce870b93a8870eca0c0f91913d12f47948ca0fd25b49c6fa7cdbeee8b" \
--local_rpc
```

##### Register Node ID 2 (Charleth, charleth.key)

```bash
register_node \
--subnet_id 1 \
--hotkey 0x2f7703Ba9953d422294079A1CB32f5d2B60E38EB \
--peer_id 12D3KooW9xdCjPXcHcyhunPZxCTdrCcbxEGh4s2PGvtoot2iz4qk \
--bootnode_peer_id 12D3KooW9xdCjPXcHcyhunPZxCTdrCcbxEGh4s2PGvtoot2iz4ql \
--bootnode /ip4/127.00.1/tcp/38962/p2p/12D3KooW9xdCjPXcHcyhunPZxCTdrCcbxEGh4s2PGvtoot2iz4qk \
--client_peer_id 12D3KooW9xdCjPXcHcyhunPZxCTdrCcbxEGh4s2PGvtoot2iz4qm \
--delegate_reward_rate 0.125 \
--stake_to_be_added 200.00 \
--max_burn_amount 100.00 \
--private_key "0x0b6e18cafb6ed99687ec547bd28139cafdd2bffe70e6b688025de6b445aa5c5b" \
--local_rpc
```

##### Register Node ID 3 (Dorothy, dorothy.key)

```bash
register_node \
--subnet_id 1 \
--hotkey 0x294BFfC18b5321264f55c517Aca2963bEF9D29EA \
--peer_id 12D3KooWD1BgwEJGUXz3DsKVXGFq3VcmHRjeX56NKpyEa1QAP6uV \
--bootnode_peer_id 12D3KooWD1BgwEJGUXz3DsKVXGFq3VcmHRjeX56NKpyEa1QAP6uW \
--bootnode /ip4/127.00.1/tcp/38963/p2p/12D3KooWD1BgwEJGUXz3DsKVXGFq3VcmHRjeX56NKpyEa1QAP6uV \
--client_peer_id 12D3KooWD1BgwEJGUXz3DsKVXGFq3VcmHRjeX56NKpyEa1QAP6uX \
--delegate_reward_rate 0.125 \
--stake_to_be_added 200.00 \
--max_burn_amount 100.00 \
--private_key "0x39539ab1876910bbf3a223d84a29e28f1cb4e2e456503e7e91ed39b2e7223d68" \
--local_rpc
```

##### Optional Node ID 4 (Faith, faith.key)

```bash
register_node \
--subnet_id 1 \
--hotkey 0xD4eb2503fA9F447CCa7b78D9a86F2fdbc964401e \
--peer_id 12D3KooWF963f4jiFX26xDKu7BrqtVYTx4Jk8rUQQUxwiJQjVFWH \
--bootnode_peer_id 12D3KooWF963f4jiFX26xDKu7BrqtVYTx4Jk8rUQQUxwiJQjVFWI \
--bootnode /ip4/127.00.1/tcp/38964/p2p/12D3KooWF963f4jiFX26xDKu7BrqtVYTx4Jk8rUQQUxwiJQjVFWH \
--client_peer_id 12D3KooWF963f4jiFX26xDKu7BrqtVYTx4Jk8rUQQUxwiJQjVFWJ \
--delegate_reward_rate 0.125 \
--stake_to_be_added 200.00 \
--max_burn_amount 100.00 \
--private_key "0xb9d2ea9a615f3165812e8d44de0d24da9bbd164b65c4f0573e1ce2c8dbd9c8df" \
--local_rpc
```

#### Run Nodes

##### Start Bootnode

```bash
python -m subnet.cli.run_node \
--private_key_path alith.key \
--port 38960 \
--subnet_id 1 \
--is_bootstrap \
--local_rpc
```

##### Start Node ID 1 (Baltathar)

We use the bootnodes peer id (alith.key) in node01's bootnode so Alith can connect (subnet requires on-chain proof-of-stake for connection).

```bash
python -m subnet.cli.run_node \
--private_key_path baltathar.key \
--port 38961 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 1 \
--local_rpc \
--tensor_private_key "0x6cbf451fc5850e75cd78055363725dcf8c80b3f1dfb9c29d131fece6dfb72490"
```

##### Start Node ID 2 (Charleth)

```bash
python -m subnet.cli.run_node \
--private_key_path charleth.key \
--port 38962 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 2 \
--local_rpc \
--tensor_private_key "0x51b7c50c1cd27de89a361210431e8f03a7ddda1a0c8c5ff4e4658ca81ac02720"
```

##### Start Node ID 3 (Dorothy)

```bash
python -m subnet.cli.run_node \
--private_key_path dorothy.key \
--port 38963 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 3 \
--local_rpc \
--tensor_private_key "0xa1983be71acf4b323612067ac9ae91308da19c2956b227618e8c611bd4746056"
```

##### Optional Start Node ID 4 (Faith)

```bash
python -m subnet.cli.run_node \
--private_key_path faith.key \
--port 38964 \
--bootstrap /ip4/127.0.0.1/tcp/38960/p2p/12D3KooWAkRWUdmXy5tkGQ1oUKxx2W4sXxsWr4ekrcvLCbA3BQTf \
--subnet_id 1 \
--subnet_node_id 4 \
--local_rpc \
--tensor_private_key "0x1dd4fd336c448379240f5e0ce4a57d574481c9981260e036f3877af6b663c927"
```

#### Delegate Stake To Subnet

This requires a minimum delegate stake of 0.01% of the total supply.

#### Activate Subnet

Activate the subnet from the owners coldkey (Alith).

```bash
python -m subnet.cli.activate_subnet \
--subnet_id 1 \
--private_key "0x5fb92d6e98884f76de468fa3f6278f8807c48bebc13595d45af5bdc4da702133"
```

### Code Quality

This project uses several tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking
- **pytest**: Testing

Run all quality checks:

```bash
make lint
make test
```

### Pre-commit Hooks

Install pre-commit hooks:

```bash
pre-commit install
```

## Documentation

Coming soon...

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
