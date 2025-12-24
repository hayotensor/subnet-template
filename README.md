# py-libp2p-subnet

A Python libp2p subnet template framework implementation.

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

#### Start Bootnode

```bash
python -m subnet.cli.run_bootnode_v2 \
--identity_path ed25519-bootnode.key \
--port 38959
```

#### Start Peers (Nodes)

##### Start Node 1 (Alith)

```bash
python -m subnet.cli.run_node_v2 \
--identity_path alith-ed25519.key \
--port 38960 \
--bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
```

##### Start Node 2 (Baltathar)

```bash
python -m subnet.cli.run_node_v2 \
--identity_path baltathar-ed25519.key \
--port 38961 \
--bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
```

##### Start Node 3 (Charleth)

```bash
python -m subnet.cli.run_node_v2 \
--identity_path charleth-ed25519.key \
--port 38962 \
--bootstrap /ip4/127.0.0.1/tcp/38959/p2p/12D3KooWLGmub3LXuKQixBD5XwNW4PtSfnrysYzqs1oj19HxMUCF
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
