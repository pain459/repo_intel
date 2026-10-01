from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.runtime import CommandResult
from repo_intel.setup.actions import execute_setup_action, plan_setup_actions
from repo_intel.setup.files import prepare_setup_files
from repo_intel.setup.models import HardwareProfile, ModelRecommendation, SetupActionKind


class StatefulSetupRunner:
    def __init__(self, *, fail_qwen_once: bool = False) -> None:
        self.embedding_installed = False
        self.qwen_installed = False
        self.qdrant_running = False
        self.fail_qwen_once = fail_qwen_once
        self.calls: list[tuple[str, ...]] = []

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
        self.calls.append(command)
        if command[1:3] == ("pull", "nomic-embed-text"):
            self.embedding_installed = True
            return CommandResult(command, 0, "", "")
        if command[1:3] == ("pull", "qwen2.5-coder:7b"):
            if self.fail_qwen_once:
                self.fail_qwen_once = False
                return CommandResult(command, 1, "private", "secret")
            self.qwen_installed = True
            return CommandResult(command, 0, "", "")
        if "compose" in command:
            self.qdrant_running = True
            return CommandResult(command, 0, "", "")
        raise AssertionError(f"unexpected action: {command}")


def test_approved_setup_is_idempotent_after_success(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)
    prepared = prepare_setup_files(app_paths)
    runner = StatefulSetupRunner()
    actions = plan_setup_actions(_report(runner), prepared.paths, runner)

    results = tuple(execute_setup_action(action, runner) for action in actions)

    assert tuple(result.kind for result in results) == (
        SetupActionKind.PULL_EMBEDDING,
        SetupActionKind.PULL_QWEN,
        SetupActionKind.START_QDRANT,
    )
    first_calls = tuple(runner.calls)

    second_preparation = prepare_setup_files(app_paths)
    second_actions = plan_setup_actions(_report(runner), second_preparation.paths, runner)

    assert second_preparation.changed_paths == ()
    assert second_actions == ()
    assert tuple(runner.calls) == first_calls


def test_rerun_after_midway_failure_plans_only_unfinished_work(tmp_path: Path) -> None:
    prepared = prepare_setup_files(_app_paths(tmp_path))
    runner = StatefulSetupRunner(fail_qwen_once=True)
    actions = plan_setup_actions(_report(runner), prepared.paths, runner)

    execute_setup_action(actions[0], runner)
    with pytest.raises(RepoIntelError):
        execute_setup_action(actions[1], runner)

    rerun = plan_setup_actions(_report(runner), prepared.paths, runner)

    assert tuple(action.kind for action in rerun) == (
        SetupActionKind.PULL_QWEN,
        SetupActionKind.START_QDRANT,
    )


def _report(runner: StatefulSetupRunner) -> DoctorReport:
    return DoctorReport(
        checks=(
            _check("ollama", CheckState.HEALTHY),
            _check("docker", CheckState.HEALTHY),
            _check(
                "qdrant",
                CheckState.HEALTHY if runner.qdrant_running else CheckState.STOPPED,
            ),
            _check(
                "nomic-embed-text",
                CheckState.INSTALLED if runner.embedding_installed else CheckState.MISSING,
            ),
            _check(
                "qwen2.5-coder:7b",
                CheckState.INSTALLED if runner.qwen_installed else CheckState.MISSING,
                required=False,
            ),
        ),
        hardware=HardwareProfile(32 * 1024**3, "arm64", None, complete=True),
        recommendation=ModelRecommendation(
            "qwen2.5-coder:7b",
            "32 GiB detected.",
            uncertain=False,
        ),
    )


def _check(
    name: str,
    state: CheckState,
    *,
    required: bool = True,
) -> DiagnosticCheck:
    return DiagnosticCheck(name, state, f"{name}: {state.value}", required)


def _app_paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "Application Root"
    return AppPaths(root / "config", root / "data", root / "cache", root / "logs")
