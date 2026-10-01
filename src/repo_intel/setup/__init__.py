"""Platform-aware setup and model recommendation."""

from repo_intel.setup.hardware import inspect_hardware
from repo_intel.setup.models import (
    AcceleratorKind,
    HardwareProfile,
    ModelRecommendation,
    PreparedSetup,
    SetupPaths,
)
from repo_intel.setup.recommendation import recommend_qwen

__all__ = [
    "AcceleratorKind",
    "HardwareProfile",
    "ModelRecommendation",
    "PreparedSetup",
    "SetupPaths",
    "inspect_hardware",
    "recommend_qwen",
]
