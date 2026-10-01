"""Immutable values shared by setup components."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AcceleratorKind(StrEnum):
    """Accelerators supported by the initial model policy."""

    APPLE_METAL = "apple_metal"
    NVIDIA_CUDA = "nvidia_cuda"


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """Available evidence used for local model sizing."""

    memory_bytes: int | None
    architecture: str
    accelerator: AcceleratorKind | None
    complete: bool


@dataclass(frozen=True, slots=True)
class ModelRecommendation:
    """A coding-model recommendation with its confidence."""

    model: str
    reason: str
    uncertain: bool


@dataclass(frozen=True, slots=True)
class SetupPaths:
    """Platform-native files and directories owned by setup."""

    user_config: Path
    compose_file: Path
    qdrant_data_dir: Path


@dataclass(frozen=True, slots=True)
class PreparedSetup:
    """Result of idempotently preparing local setup state."""

    paths: SetupPaths
    changed_paths: tuple[Path, ...]


class SetupActionKind(StrEnum):
    """External setup changes that require individual consent."""

    PULL_EMBEDDING = "pull_embedding"
    PULL_QWEN = "pull_qwen"
    START_QDRANT = "start_qdrant"


@dataclass(frozen=True, slots=True)
class SetupAction:
    """One fully specified external action awaiting consent."""

    kind: SetupActionKind
    description: str
    args: tuple[str, ...]
    timeout_seconds: float
    stream: bool
    env: Mapping[str, str] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SetupActionResult:
    """Successful completion of one approved setup action."""

    kind: SetupActionKind
    succeeded: bool


__all__ = [
    "AcceleratorKind",
    "HardwareProfile",
    "ModelRecommendation",
    "PreparedSetup",
    "SetupAction",
    "SetupActionKind",
    "SetupActionResult",
    "SetupPaths",
]
