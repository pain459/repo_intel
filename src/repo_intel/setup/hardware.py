"""Platform-specific hardware evidence gathering."""

import platform as host_platform
from pathlib import Path

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import PlatformKind
from repo_intel.runtime import CommandRunner
from repo_intel.setup.models import AcceleratorKind, HardwareProfile

_PROBE_TIMEOUT_SECONDS = 2.0


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _macos_memory(runner: CommandRunner) -> int | None:
    sysctl = runner.which("sysctl")
    if sysctl is None:
        return None
    result = runner.run(
        [str(sysctl), "-n", "hw.memsize"],
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or result.timed_out:
        return None
    return _positive_int(result.stdout)


def _ubuntu_memory(meminfo_path: Path) -> int | None:
    try:
        lines = meminfo_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None

    for line in lines:
        key, separator, value = line.partition(":")
        if key != "MemTotal" or not separator:
            continue
        parts = value.split()
        if len(parts) != 2 or parts[1] != "kB":
            return None
        kibibytes = _positive_int(parts[0])
        return None if kibibytes is None else kibibytes * 1024
    return None


def _ubuntu_accelerator(runner: CommandRunner) -> AcceleratorKind | None:
    nvidia_smi = runner.which("nvidia-smi")
    if nvidia_smi is None:
        return None
    result = runner.run(
        [str(nvidia_smi), "--query-gpu=name", "--format=csv,noheader"],
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode == 0 and not result.timed_out and result.stdout.strip():
        return AcceleratorKind.NVIDIA_CUDA
    return None


def inspect_hardware(
    platform: PlatformKind,
    runner: CommandRunner,
    *,
    architecture: str | None = None,
    meminfo_path: Path = Path("/proc/meminfo"),
) -> HardwareProfile:
    """Gather only the evidence required by the Qwen sizing policy."""
    detected_architecture = host_platform.machine() if architecture is None else architecture
    if platform is PlatformKind.MACOS:
        memory = _macos_memory(runner)
        accelerator = (
            AcceleratorKind.APPLE_METAL
            if detected_architecture.lower() in {"arm64", "aarch64"}
            else None
        )
        return HardwareProfile(
            memory,
            detected_architecture,
            accelerator,
            complete=memory is not None and bool(detected_architecture),
        )
    if platform is PlatformKind.UBUNTU:
        memory = _ubuntu_memory(meminfo_path)
        accelerator = _ubuntu_accelerator(runner)
        return HardwareProfile(
            memory,
            detected_architecture,
            accelerator,
            complete=(
                memory is not None and bool(detected_architecture) and accelerator is not None
            ),
        )
    raise RepoIntelError(
        f"Unsupported platform kind: {platform}",
        ExitCode.PLATFORM,
        hint="repo_intel v1 supports macOS and Ubuntu.",
    )


__all__ = ["inspect_hardware"]
