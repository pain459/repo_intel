from collections.abc import Mapping, Sequence
from pathlib import Path

from repo_intel.diagnostics.doctor import run_doctor
from repo_intel.diagnostics.models import CheckState
from repo_intel.errors import ExitCode
from repo_intel.platform import PlatformKind
from repo_intel.runtime import CommandResult, JsonResponse
from repo_intel.runtime.http import HttpState
from repo_intel.setup.models import AcceleratorKind, HardwareProfile


class RecordingRunner:
    def __init__(self) -> None:
        self.which_calls: list[str] = []
        self.run_calls: list[tuple[str, ...]] = []

    def which(self, executable: str) -> Path | None:
        self.which_calls.append(executable)
        return Path(f"/Tool Box/{executable}")

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
        self.run_calls.append(command)
        return CommandResult(command, 0, "28.0", "")


class RecordingHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> JsonResponse:
        assert timeout_seconds == 2.0
        self.calls.append(url)
        if url.endswith("/api/tags"):
            return JsonResponse(
                HttpState.OK,
                200,
                {
                    "models": [
                        {"name": "nomic-embed-text:latest", "size": 1},
                        {"name": "qwen3-coder:30b", "size": 2},
                    ]
                },
            )
        return JsonResponse(HttpState.OK, 200, "healthz check passed")


def test_doctor_workflow_is_complete_deterministic_and_read_only(tmp_path: Path) -> None:
    nonexistent_application_root = tmp_path / "must not be created"
    runner = RecordingRunner()
    http = RecordingHttp()
    hardware = HardwareProfile(
        memory_bytes=64 * 1024**3,
        architecture="arm64",
        accelerator=AcceleratorKind.APPLE_METAL,
        complete=True,
    )

    report = run_doctor(
        PlatformKind.MACOS,
        runner,
        http,
        hardware_profile=hardware,
    )

    assert [(check.name, check.state) for check in report.checks] == [
        ("git", CheckState.INSTALLED),
        ("rg", CheckState.INSTALLED),
        ("ollama", CheckState.HEALTHY),
        ("docker", CheckState.HEALTHY),
        ("qdrant", CheckState.HEALTHY),
        ("nomic-embed-text", CheckState.INSTALLED),
        ("qwen3-coder:30b", CheckState.INSTALLED),
    ]
    assert report.exit_code is ExitCode.SUCCESS
    assert report.recommendation.model == "qwen3-coder:30b"
    assert runner.which_calls == ["git", "rg", "ollama", "docker"]
    assert runner.run_calls == [("/Tool Box/docker", "info", "--format", "{{.ServerVersion}}")]
    assert http.calls == [
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:6333/healthz",
    ]
    assert not nonexistent_application_root.exists()
    assert all("pull" not in call and "compose" not in call for call in runner.run_calls)
