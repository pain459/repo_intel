"""Platform-aware setup and model recommendation."""

from repo_intel.setup.hardware import inspect_hardware
from repo_intel.setup.models import AcceleratorKind, HardwareProfile, ModelRecommendation
from repo_intel.setup.recommendation import recommend_qwen

__all__ = [
    "AcceleratorKind",
    "HardwareProfile",
    "ModelRecommendation",
    "inspect_hardware",
    "recommend_qwen",
]
