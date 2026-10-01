"""Select the supported adapter for the current host."""

import platform as host_platform
from collections.abc import Mapping
from pathlib import Path

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform.base import PlatformAdapter
from repo_intel.platform.macos import MacOSPlatform
from repo_intel.platform.ubuntu import UbuntuPlatform


def _read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    release: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        release[key] = value.strip().strip("\"'")
    return release


def _unsupported(system: str) -> RepoIntelError:
    return RepoIntelError(
        f"Unsupported operating system: {system}",
        ExitCode.PLATFORM,
        hint="repo_intel v1 supports macOS and Ubuntu.",
    )


def detect_platform(
    *,
    system: str | None = None,
    os_release: Mapping[str, str] | None = None,
) -> PlatformAdapter:
    """Return the adapter for macOS or Ubuntu, rejecting every other host."""
    detected_system = system or host_platform.system()
    if detected_system == "Darwin":
        return MacOSPlatform()
    if detected_system == "Linux":
        release = _read_os_release() if os_release is None else os_release
        if release.get("ID", "").lower() == "ubuntu":
            return UbuntuPlatform()
    raise _unsupported(detected_system)
