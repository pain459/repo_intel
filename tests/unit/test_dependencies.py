from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.diagnostics.dependencies import check_executable
from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import ExitCode
from repo_intel.runtime import CommandResult
from repo_intel.setup.models import HardwareProfile, ModelRecommendation


class PathRunner:
    def __init__(self, paths: Mapping[str, Path]) -> None:
        self.paths = dict(paths)

    def which(self, executable: str) -> Path | None:
        return self.paths.get(executable)

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult:
        raise AssertionError(f"unexpected command: {args}")


@pytest.mark.parametrize("name", ["git", "rg", "ollama", "docker"])
def test_installed_executable_reports_fixed_summary_without_path(name: str) -> None:
    private_path = Path(f"/private/Secret User/bin/{name}")

    check = check_executable(
        name,
        PathRunner({name: private_path}),
        guidance=f"Install {name} safely.",
    )

    assert check == DiagnosticCheck(
        name=name,
        state=CheckState.INSTALLED,
        summary=f"{name} is installed.",
        required=True,
    )
    assert str(private_path) not in repr(check)


@pytest.mark.parametrize("name", ["git", "rg", "ollama", "docker"])
def test_missing_executable_reports_fixed_guidance(name: str) -> None:
    check = check_executable(
        name,
        PathRunner({}),
        guidance=f"Install {name} safely.",
    )

    assert check.state is CheckState.MISSING
    assert check.summary == f"{name} is missing."
    assert check.guidance == f"Install {name} safely."
    assert check.required is True


def test_doctor_report_prioritizes_external_service_failure() -> None:
    report = _report(
        DiagnosticCheck("git", CheckState.MISSING, "git is missing.", required=True),
        DiagnosticCheck("qdrant", CheckState.STOPPED, "Qdrant is stopped.", required=True),
    )

    assert report.exit_code is ExitCode.EXTERNAL_SERVICE


def test_doctor_report_uses_dependency_code_for_required_missing_item() -> None:
    report = _report(
        DiagnosticCheck("nomic-embed-text", CheckState.MISSING, "Model missing.", required=True)
    )

    assert report.exit_code is ExitCode.DEPENDENCY


def test_optional_qwen_model_does_not_fail_doctor() -> None:
    report = _report(
        DiagnosticCheck("qwen", CheckState.MISSING, "Recommended model missing.", required=False)
    )

    assert report.exit_code is ExitCode.SUCCESS


def _report(*checks: DiagnosticCheck) -> DoctorReport:
    return DoctorReport(
        checks=checks,
        hardware=HardwareProfile(None, "unknown", None, complete=False),
        recommendation=ModelRecommendation("qwen2.5-coder:1.5b", "Fallback.", uncertain=True),
    )
