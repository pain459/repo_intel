from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repo_intel.cli import setup as cli_setup
from repo_intel.cli.app import app
from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.runtime import CommandResult
from repo_intel.setup.models import HardwareProfile, ModelRecommendation, SetupActionKind

runner = CliRunner()


class CliActionRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.run_calls: list[tuple[str, ...]] = []

    def which(self, executable: str) -> Path | None:
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
        return CommandResult(
            command,
            1 if self.fail else 0,
            "SENTINEL_OUTPUT",
            "SENTINEL_ERROR",
        )


def test_first_run_creates_files_and_no_input_declines_all_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_runner = _arrange_setup(monkeypatch, tmp_path, reports=[_incomplete_report()] * 2)

    result = runner.invoke(app, ["setup", "--no-input"])

    assert result.exit_code == 0
    assert (tmp_path / "config" / "config.toml").is_file()
    assert (tmp_path / "config" / "qdrant.compose.yaml").is_file()
    assert "Proposed: Pull required embedding model nomic-embed-text." in result.stdout
    assert "Proposed: Pull recommended coding model qwen2.5-coder:7b." in result.stdout
    assert "Proposed: Start the managed Qdrant service." in result.stdout
    assert "Skipped unapproved setup actions." in result.stdout
    assert action_runner.run_calls == []


def test_interactive_setup_confirms_each_action_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_runner = _arrange_setup(monkeypatch, tmp_path, reports=[_incomplete_report()] * 2)

    result = runner.invoke(app, ["setup"], input="y\nn\ny\n")

    assert result.exit_code == 0
    assert result.stdout.count("Proceed?") == 3
    assert [call[1] for call in action_runner.run_calls] == ["pull", "compose"]
    assert all("qwen2.5-coder:7b" not in call for call in action_runner.run_calls)


def test_eof_cancels_current_and_remaining_actions_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_runner = _arrange_setup(monkeypatch, tmp_path, reports=[_incomplete_report()] * 2)

    result = runner.invoke(app, ["setup"], input="")

    assert result.exit_code == 0
    assert "Setup confirmation cancelled; remaining actions were skipped." in result.stdout
    assert action_runner.run_calls == []


@pytest.mark.parametrize(
    ("flag", "expected_kind"),
    [
        ("--pull-embedding", SetupActionKind.PULL_EMBEDDING),
        ("--pull-qwen", SetupActionKind.PULL_QWEN),
        ("--start-qdrant", SetupActionKind.START_QDRANT),
    ],
)
def test_explicit_flag_approves_only_its_matching_action(
    flag: str,
    expected_kind: SetupActionKind,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_runner = _arrange_setup(monkeypatch, tmp_path, reports=[_incomplete_report()] * 2)

    result = runner.invoke(app, ["setup", "--no-input", flag])

    assert result.exit_code == 0
    assert len(action_runner.run_calls) == 1
    command = action_runner.run_calls[0]
    if expected_kind is SetupActionKind.PULL_EMBEDDING:
        assert command[-1] == "nomic-embed-text"
    elif expected_kind is SetupActionKind.PULL_QWEN:
        assert command[-1] == "qwen2.5-coder:7b"
    else:
        assert command[1] == "compose"


def test_failed_approved_action_uses_typed_exit_without_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_runner = _arrange_setup(
        monkeypatch,
        tmp_path,
        reports=[_incomplete_report()],
        fail=True,
    )

    result = runner.invoke(app, ["setup", "--no-input", "--pull-embedding"])

    assert result.exit_code == ExitCode.EXTERNAL_SERVICE
    assert len(action_runner.run_calls) == 1
    assert "The approved setup action did not complete." in result.stdout
    assert "SENTINEL_OUTPUT" not in result.stdout
    assert "SENTINEL_ERROR" not in result.stdout


def test_second_healthy_run_reports_no_changes_or_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_paths = _app_paths(tmp_path)
    from repo_intel.setup.files import prepare_setup_files

    prepare_setup_files(app_paths)
    action_runner = _arrange_setup(
        monkeypatch,
        tmp_path,
        reports=[_healthy_report(), _healthy_report()],
    )

    result = runner.invoke(app, ["setup", "--no-input"])

    assert result.exit_code == 0
    assert "Local setup files are already current." in result.stdout
    assert "No external setup actions are needed." in result.stdout
    assert action_runner.run_calls == []


def test_unsupported_platform_fails_before_creating_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_doctor() -> DoctorReport:
        raise RepoIntelError(
            "Unsupported operating system: Windows",
            ExitCode.PLATFORM,
            hint="repo_intel v1 supports macOS and Ubuntu.",
        )

    monkeypatch.setattr(cli_setup, "build_doctor_report", fail_doctor)
    monkeypatch.setattr(cli_setup, "resolve_app_paths", lambda: _app_paths(tmp_path))

    result = runner.invoke(app, ["setup", "--no-input"])

    assert result.exit_code == ExitCode.PLATFORM
    assert "Unsupported operating system" in result.stdout
    assert not (tmp_path / "config").exists()


def _arrange_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    reports: list[DoctorReport],
    fail: bool = False,
) -> CliActionRunner:
    report_iterator: Iterator[DoctorReport] = iter(reports)
    action_runner = CliActionRunner(fail=fail)
    monkeypatch.setattr(cli_setup, "build_doctor_report", lambda: next(report_iterator))
    monkeypatch.setattr(cli_setup, "resolve_app_paths", lambda: _app_paths(tmp_path))
    monkeypatch.setattr(cli_setup, "new_command_runner", lambda: action_runner)
    return action_runner


def _incomplete_report() -> DoctorReport:
    return _report(
        DiagnosticCheck("ollama", CheckState.HEALTHY, "Ollama healthy.", True),
        DiagnosticCheck("docker", CheckState.HEALTHY, "Docker healthy.", True),
        DiagnosticCheck("qdrant", CheckState.STOPPED, "Qdrant stopped.", True),
        DiagnosticCheck("nomic-embed-text", CheckState.MISSING, "Embedding missing.", True),
        DiagnosticCheck("qwen2.5-coder:7b", CheckState.MISSING, "Qwen missing.", False),
    )


def _healthy_report() -> DoctorReport:
    return _report(
        DiagnosticCheck("ollama", CheckState.HEALTHY, "Ollama healthy.", True),
        DiagnosticCheck("docker", CheckState.HEALTHY, "Docker healthy.", True),
        DiagnosticCheck("qdrant", CheckState.HEALTHY, "Qdrant healthy.", True),
        DiagnosticCheck(
            "nomic-embed-text",
            CheckState.INSTALLED,
            "Embedding installed.",
            True,
        ),
        DiagnosticCheck("qwen2.5-coder:7b", CheckState.INSTALLED, "Qwen installed.", False),
    )


def _report(*checks: DiagnosticCheck) -> DoctorReport:
    return DoctorReport(
        checks=checks,
        hardware=HardwareProfile(32 * 1024**3, "arm64", None, complete=True),
        recommendation=ModelRecommendation(
            "qwen2.5-coder:7b",
            "32 GiB memory detected.",
            uncertain=False,
        ),
    )


def _app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "cache",
        tmp_path / "logs",
    )
