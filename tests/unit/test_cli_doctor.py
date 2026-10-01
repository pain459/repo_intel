import pytest
from typer.testing import CliRunner

from repo_intel.cli import doctor as cli_doctor
from repo_intel.cli.app import app
from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import PlatformKind
from repo_intel.setup.guidance import installation_guidance
from repo_intel.setup.models import HardwareProfile, ModelRecommendation

runner = CliRunner()


@pytest.mark.parametrize("dependency", ["git", "rg", "ollama", "docker"])
def test_installation_guidance_is_platform_specific(dependency: str) -> None:
    macos = installation_guidance(PlatformKind.MACOS, dependency)
    ubuntu = installation_guidance(PlatformKind.UBUNTU, dependency)

    assert macos != ubuntu
    assert dependency.lower() in macos.lower() or dependency == "rg"
    assert dependency.lower() in ubuntu.lower() or dependency == "rg"


def test_doctor_renders_checks_and_certain_recommendation_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        ExitCode.SUCCESS,
        uncertain=False,
        checks=(
            DiagnosticCheck("git", CheckState.INSTALLED, "git is installed.", True),
            DiagnosticCheck("qdrant", CheckState.HEALTHY, "Qdrant is healthy.", True),
        ),
    )
    monkeypatch.setattr(cli_doctor, "build_doctor_report", lambda: report)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "git: installed — git is installed.",
        "qdrant: healthy — Qdrant is healthy.",
        "Recommended Qwen model: qwen2.5-coder:7b",
        "Recommendation basis: 32 GiB memory detected.",
    ]


def test_doctor_labels_uncertain_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report(ExitCode.SUCCESS, uncertain=True)
    monkeypatch.setattr(cli_doctor, "build_doctor_report", lambda: report)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Recommendation confidence: uncertain" in result.stdout


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        (CheckState.MISSING, ExitCode.DEPENDENCY),
        (CheckState.STOPPED, ExitCode.EXTERNAL_SERVICE),
        (CheckState.UNHEALTHY, ExitCode.EXTERNAL_SERVICE),
    ],
)
def test_doctor_uses_report_exit_code(
    state: CheckState,
    expected_code: ExitCode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        expected_code,
        uncertain=False,
        checks=(DiagnosticCheck("required", state, f"required is {state.value}.", True),),
    )
    monkeypatch.setattr(cli_doctor, "build_doctor_report", lambda: report)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == expected_code


def test_doctor_prints_only_typed_error_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SENTINEL_PRIVATE_VALUE"

    def fail() -> DoctorReport:
        try:
            raise ValueError(secret)
        except ValueError as cause:
            raise RepoIntelError(
                "Diagnostics could not run.",
                ExitCode.DEPENDENCY,
                hint="Install the missing dependency.",
            ) from cause

    monkeypatch.setattr(cli_doctor, "build_doctor_report", fail)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == ExitCode.DEPENDENCY
    assert "Diagnostics could not run." in result.stdout
    assert "Install the missing dependency." in result.stdout
    assert secret not in result.stdout


def test_unexpected_doctor_failure_is_not_converted_to_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> DoctorReport:
        raise RuntimeError("unexpected sentinel")

    monkeypatch.setattr(cli_doctor, "build_doctor_report", fail)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == ExitCode.INTERNAL
    assert isinstance(result.exception, RuntimeError)


def _report(
    expected_code: ExitCode,
    *,
    uncertain: bool,
    checks: tuple[DiagnosticCheck, ...] = (),
) -> DoctorReport:
    report = DoctorReport(
        checks=checks,
        hardware=HardwareProfile(32 * 1024**3, "arm64", None, complete=True),
        recommendation=ModelRecommendation(
            "qwen2.5-coder:7b",
            "32 GiB memory detected.",
            uncertain,
        ),
    )
    assert report.exit_code is expected_code
    return report
