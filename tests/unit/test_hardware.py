from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.platform import PlatformKind
from repo_intel.runtime import CommandResult
from repo_intel.setup.hardware import inspect_hardware
from repo_intel.setup.models import AcceleratorKind

GIB = 1024**3


class FakeRunner:
    def __init__(
        self,
        *,
        executables: Mapping[str, Path] | None = None,
        results: Mapping[tuple[str, ...], CommandResult] | None = None,
    ) -> None:
        self.executables = dict(executables or {})
        self.results = dict(results or {})
        self.calls: list[tuple[str, ...]] = []

    def which(self, executable: str) -> Path | None:
        return self.executables.get(executable)

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult:
        del timeout_seconds, env, stream
        command = tuple(args)
        self.calls.append(command)
        return self.results[command]


def test_macos_reads_memory_through_discovered_sysctl_and_infers_metal() -> None:
    command = ("/Tool Box/sysctl", "-n", "hw.memsize")
    runner = FakeRunner(
        executables={"sysctl": Path("/Tool Box/sysctl")},
        results={command: CommandResult(command, 0, str(64 * GIB), "")},
    )

    profile = inspect_hardware(PlatformKind.MACOS, runner, architecture="arm64")

    assert profile.memory_bytes == 64 * GIB
    assert profile.architecture == "arm64"
    assert profile.accelerator is AcceleratorKind.APPLE_METAL
    assert profile.complete is True
    assert runner.calls == [command]


def test_intel_macos_does_not_infer_an_accelerator() -> None:
    command = ("/usr/bin/sysctl", "-n", "hw.memsize")
    runner = FakeRunner(
        executables={"sysctl": Path("/usr/bin/sysctl")},
        results={command: CommandResult(command, 0, str(32 * GIB), "")},
    )

    profile = inspect_hardware(PlatformKind.MACOS, runner, architecture="x86_64")

    assert profile.accelerator is None
    assert profile.complete is True


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(("sysctl",), 1, "private-output", "private-error"),
        CommandResult(("sysctl",), 0, "not-a-number", ""),
        CommandResult(("sysctl",), 0, "0", ""),
    ],
)
def test_macos_marks_failed_or_malformed_memory_evidence_incomplete(
    result: CommandResult,
) -> None:
    command = ("/usr/bin/sysctl", "-n", "hw.memsize")
    runner = FakeRunner(
        executables={"sysctl": Path("/usr/bin/sysctl")},
        results={command: CommandResult(command, result.returncode, result.stdout, result.stderr)},
    )

    profile = inspect_hardware(PlatformKind.MACOS, runner, architecture="arm64")

    assert profile.memory_bytes is None
    assert profile.complete is False
    assert "private" not in repr(profile)


def test_macos_without_sysctl_returns_incomplete_profile_without_running() -> None:
    runner = FakeRunner()

    profile = inspect_hardware(PlatformKind.MACOS, runner, architecture="arm64")

    assert profile.memory_bytes is None
    assert profile.complete is False
    assert runner.calls == []


def test_ubuntu_reads_unicode_meminfo_and_confirms_nvidia_cuda(tmp_path: Path) -> None:
    meminfo = tmp_path / "mémoire système"
    meminfo.write_text("MemTotal:       50331648 kB\nMemFree: 1 kB\n", encoding="utf-8")
    command = ("/opt/NVIDIA Tools/nvidia-smi", "--query-gpu=name", "--format=csv,noheader")
    runner = FakeRunner(
        executables={"nvidia-smi": Path("/opt/NVIDIA Tools/nvidia-smi")},
        results={command: CommandResult(command, 0, "GPU", "")},
    )

    profile = inspect_hardware(
        PlatformKind.UBUNTU,
        runner,
        architecture="x86_64",
        meminfo_path=meminfo,
    )

    assert profile.memory_bytes == 50_331_648 * 1024
    assert profile.accelerator is AcceleratorKind.NVIDIA_CUDA
    assert profile.complete is True
    assert runner.calls == [command]


def test_ubuntu_without_nvidia_smi_is_conservatively_incomplete(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 16777216 kB\n", encoding="utf-8")

    profile = inspect_hardware(
        PlatformKind.UBUNTU,
        FakeRunner(),
        architecture="x86_64",
        meminfo_path=meminfo,
    )

    assert profile.memory_bytes == 16 * GIB
    assert profile.accelerator is None
    assert profile.complete is False


@pytest.mark.parametrize("contents", ["MemFree: 10 kB\n", "MemTotal: nope kB\n"])
def test_ubuntu_malformed_memory_evidence_is_incomplete(
    tmp_path: Path,
    contents: str,
) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(contents, encoding="utf-8")

    profile = inspect_hardware(
        PlatformKind.UBUNTU,
        FakeRunner(),
        architecture="x86_64",
        meminfo_path=meminfo,
    )

    assert profile.memory_bytes is None
    assert profile.complete is False


def test_ubuntu_missing_meminfo_is_incomplete(tmp_path: Path) -> None:
    profile = inspect_hardware(
        PlatformKind.UBUNTU,
        FakeRunner(),
        architecture="x86_64",
        meminfo_path=tmp_path / "missing",
    )

    assert profile.memory_bytes is None
    assert profile.complete is False
