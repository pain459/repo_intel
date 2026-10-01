"""Platform-aware setup and model recommendation."""

from repo_intel.setup.hardware import inspect_hardware
from repo_intel.setup.models import (
    AcceleratorKind,
    HardwareProfile,
    ModelRecommendation,
    PreparedSetup,
    SetupAction,
    SetupActionKind,
    SetupActionResult,
    SetupPaths,
)
from repo_intel.setup.recommendation import recommend_qwen

__all__ = [
    "AcceleratorKind",
    "HardwareProfile",
    "ModelRecommendation",
    "PreparedSetup",
    "SetupAction",
    "SetupActionKind",
    "SetupActionResult",
    "SetupPaths",
    "inspect_hardware",
    "recommend_qwen",
]
