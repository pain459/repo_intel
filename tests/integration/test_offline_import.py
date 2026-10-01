import importlib
import socket
import sys
from types import ModuleType

import pytest

PUBLIC_MODULES = (
    "repo_intel",
    "repo_intel.cli.app",
    "repo_intel.config",
    "repo_intel.platform",
    "repo_intel.domain",
    "repo_intel.ports",
)


def test_public_modules_import_without_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("repo_intel import attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", reject_connection)
    monkeypatch.setattr(socket.socket, "connect", reject_connection)

    original_modules: dict[str, ModuleType] = {
        name: module
        for name, module in sys.modules.items()
        if name == "repo_intel" or name.startswith("repo_intel.")
    }
    for name in tuple(original_modules):
        sys.modules.pop(name, None)

    try:
        for name in PUBLIC_MODULES:
            importlib.import_module(name)
    finally:
        for name in tuple(sys.modules):
            if name == "repo_intel" or name.startswith("repo_intel."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)
