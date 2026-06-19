from __future__ import annotations

import importlib
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_setuptools_uses_package_discovery_for_subpackages():
    setuptools_config = _load_pyproject()["tool"]["setuptools"]

    assert setuptools_config["packages"]["find"]["include"] == ["subnet*"]
    assert "protocols/config/*.example.json" in setuptools_config["package-data"]["subnet"]


def test_console_script_targets_are_importable():
    scripts = _load_pyproject()["project"]["scripts"]

    for script_name, target in scripts.items():
        module_name, function_name = target.split(":", 1)

        module = importlib.import_module(module_name)

        assert hasattr(module, function_name), f"{script_name} points at missing target {target}"


def test_dockerfile_uses_existing_node_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "subnet.api.main" not in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "subnet.cli.run_node"]' in dockerfile
    assert 'CMD ["--port", "38960"]' in dockerfile
