from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.runtime import CommandResult
from repo_intel.setup.actions import execute_setup_action, plan_setup_actions
from repo_intel.setup.models import (
    HardwareProfile,
    ModelRecommendation,
    SetupAction,
    SetupActionKind,
    SetupPaths,
)


class ActionRunner:
    def __init__(
        self,
        *,
        executables: Mapping[str, Path] | None = None,
        result: CommandResult | None = None,
        error: OSError | None = None,
    ) -> None:
        self.executables = dict(executables or {})
        self.result = result
        self.error = error
        self.calls: list[tuple[tuple[str, ...], float, bool]] = []

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
        del env
        command = tuple(args)
        self.calls.append((command, timeout_seconds, stream))
        if self.error is not None:
            raise self.error
        if self.result is None:
            return CommandResult(command, 0, "", "")
        return self.result


def test_plan_builds_exact_missing_model_and_stopped_qdrant_actions(tmp_path: Path) -> None:
    setup = SetupPaths(
        user_config=tmp_path / "config.toml",
        compose_file=tmp_path / "Config Space" / "qdrant.compose.yaml",
        qdrant_data_dir=tmp_path / "data",
    )
    report = _report(
        _check("ollama", CheckState.HEALTHY),
        _check("docker", CheckState.HEALTHY),
        _check("qdrant", CheckState.STOPPED),
        _check("nomic-embed-text", CheckState.MISSING),
        _check("qwen2.5-coder:7b", CheckState.MISSING, required=False),
    )
    runner = ActionRunner(
        executables={
            "ollama": Path("/Applications/Ollama App/ollama"),
            "docker": Path("/Applications/Docker App/docker"),
        }
    )

    actions = plan_setup_actions(report, setup, runner)

    assert actions == (
        SetupAction(
            SetupActionKind.PULL_EMBEDDING,
            "Pull required embedding model nomic-embed-text.",
            ("/Applications/Ollama App/ollama", "pull", "nomic-embed-text"),
            timeout_seconds=3_600,
            stream=True,
        ),
        SetupAction(
            SetupActionKind.PULL_QWEN,
            "Pull recommended coding model qwen2.5-coder:7b.",
            ("/Applications/Ollama App/ollama", "pull", "qwen2.5-coder:7b"),
            timeout_seconds=3_600,
            stream=True,
        ),
        SetupAction(
            SetupActionKind.START_QDRANT,
            "Start the managed Qdrant service.",
            (
                "/Applications/Docker App/docker",
                "compose",
                "--project-name",
                "repo-intel",
                "--file",
                str(setup.compose_file),
                "up",
                "--detach",
                "qdrant",
            ),
            timeout_seconds=120,
            stream=True,
        ),
    )


def test_plan_is_empty_when_models_and_qdrant_are_ready(tmp_path: Path) -> None:
    report = _report(
        _check("ollama", CheckState.HEALTHY),
        _check("docker", CheckState.HEALTHY),
        _check("qdrant", CheckState.HEALTHY),
        _check("nomic-embed-text", CheckState.INSTALLED),
        _check("qwen2.5-coder:7b", CheckState.INSTALLED, required=False),
    )

    assert plan_setup_actions(report, _setup_paths(tmp_path), ActionRunner()) == ()


def test_missing_action_executables_leave_only_report_guidance(tmp_path: Path) -> None:
    report = _report(
        _check("ollama", CheckState.MISSING),
        _check("docker", CheckState.MISSING),
        _check("qdrant", CheckState.STOPPED),
        _check("nomic-embed-text", CheckState.MISSING),
        _check("qwen2.5-coder:7b", CheckState.MISSING, required=False),
    )

    assert plan_setup_actions(report, _setup_paths(tmp_path), ActionRunner()) == ()


@pytest.mark.parametrize(
    "kind",
    [
        SetupActionKind.PULL_EMBEDDING,
        SetupActionKind.PULL_QWEN,
        SetupActionKind.START_QDRANT,
    ],
)
def test_execute_success_uses_the_action_exactly_once(kind: SetupActionKind) -> None:
    action = SetupAction(
        kind,
        "Approved action.",
        ("/Tool Box/executable", "argument with spaces"),
        timeout_seconds=120,
        stream=True,
    )
    runner = ActionRunner()

    result = execute_setup_action(action, runner)

    assert result.kind is kind
    assert result.succeeded is True
    assert runner.calls == [(("/Tool Box/executable", "argument with spaces"), 120, True)]


@pytest.mark.parametrize("timed_out", [False, True])
def test_failed_action_returns_safe_external_service_error(timed_out: bool) -> None:
    action = SetupAction(
        SetupActionKind.PULL_EMBEDDING,
        "Pull model.",
        ("/usr/bin/ollama", "pull", "nomic-embed-text"),
        timeout_seconds=3_600,
        stream=True,
    )
    result = CommandResult(
        action.args,
        124 if timed_out else 1,
        "private-output",
        "secret-error",
        timed_out=timed_out,
    )

    with pytest.raises(RepoIntelError) as raised:
        execute_setup_action(action, ActionRunner(result=result))

    assert raised.value.exit_code is ExitCode.EXTERNAL_SERVICE
    assert raised.value.hint is not None
    assert "private-output" not in str(raised.value)
    assert "secret-error" not in str(raised.value)


def test_disappearing_executable_returns_dependency_error() -> None:
    action = SetupAction(
        SetupActionKind.START_QDRANT,
        "Start Qdrant.",
        ("/missing/docker", "compose", "up"),
        timeout_seconds=120,
        stream=True,
    )

    with pytest.raises(RepoIntelError) as raised:
        execute_setup_action(
            action,
            ActionRunner(error=FileNotFoundError("private missing path")),
        )

    assert raised.value.exit_code is ExitCode.DEPENDENCY
    assert raised.value.hint is not None
    assert "private missing path" not in str(raised.value)


def _check(
    name: str,
    state: CheckState,
    *,
    required: bool = True,
) -> DiagnosticCheck:
    return DiagnosticCheck(name, state, f"{name}: {state.value}", required=required)


def _report(*checks: DiagnosticCheck) -> DoctorReport:
    return DoctorReport(
        checks=checks,
        hardware=HardwareProfile(32 * 1024**3, "arm64", None, complete=True),
        recommendation=ModelRecommendation(
            "qwen2.5-coder:7b",
            "32 GiB detected.",
            uncertain=False,
        ),
    )


def _setup_paths(tmp_path: Path) -> SetupPaths:
    return SetupPaths(
        tmp_path / "config.toml",
        tmp_path / "qdrant.compose.yaml",
        tmp_path / "qdrant",
    )
