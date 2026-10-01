"""Shared platform types."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class PlatformKind(StrEnum):
    """Platforms supported by the first release."""

    MACOS = "macos"
    UBUNTU = "ubuntu"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Platform-native application directories."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path


class PlatformAdapter(Protocol):
    """Compute platform-specific paths without creating them."""

    kind: PlatformKind

    def paths(self, *, home: Path, environ: Mapping[str, str]) -> AppPaths: ...

