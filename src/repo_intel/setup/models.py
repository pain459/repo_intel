"""Immutable values shared by setup components."""

from dataclasses import dataclass
from enum import StrEnum


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


__all__ = ["AcceleratorKind", "HardwareProfile", "ModelRecommendation"]
