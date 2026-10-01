"""Supported operating-system adapters."""

from repo_intel.platform.base import AppPaths, PlatformAdapter, PlatformKind
from repo_intel.platform.detection import detect_platform
from repo_intel.platform.macos import MacOSPlatform
from repo_intel.platform.ubuntu import UbuntuPlatform

__all__ = [
    "AppPaths",
    "MacOSPlatform",
    "PlatformAdapter",
    "PlatformKind",
    "UbuntuPlatform",
    "detect_platform",
]
