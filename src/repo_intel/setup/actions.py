"""Planning and execution of individually approved setup changes."""

from repo_intel.diagnostics.models import CheckState, DiagnosticCheck, DoctorReport
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.runtime import CommandRunner
from repo_intel.setup.models import (
    SetupAction,
    SetupActionKind,
    SetupActionResult,
    SetupPaths,
)

_MODEL_TIMEOUT_SECONDS = 3_600.0
_QDRANT_TIMEOUT_SECONDS = 120.0


def _find_check(report: DoctorReport, name: str) -> DiagnosticCheck | None:
    return next((check for check in report.checks if check.name == name), None)


def _pull_action(
    kind: SetupActionKind,
    executable: str,
    model: str,
    description: str,
) -> SetupAction:
    return SetupAction(
        kind,
        description,
        (executable, "pull", model),
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        stream=True,
    )


def plan_setup_actions(
    report: DoctorReport,
    setup: SetupPaths,
    runner: CommandRunner,
) -> tuple[SetupAction, ...]:
    """Plan possible changes from a diagnostic snapshot without executing them."""
    actions: list[SetupAction] = []
    ollama_check = _find_check(report, "ollama")
    ollama = (
        runner.which("ollama")
        if ollama_check is not None and ollama_check.state is CheckState.HEALTHY
        else None
    )
    embedding = _find_check(report, "nomic-embed-text")
    if ollama is not None and embedding is not None and embedding.state is CheckState.MISSING:
        actions.append(
            _pull_action(
                SetupActionKind.PULL_EMBEDDING,
                str(ollama),
                "nomic-embed-text",
                "Pull required embedding model nomic-embed-text.",
            )
        )

    qwen = _find_check(report, report.recommendation.model)
    if ollama is not None and qwen is not None and qwen.state is CheckState.MISSING:
        actions.append(
            _pull_action(
                SetupActionKind.PULL_QWEN,
                str(ollama),
                report.recommendation.model,
                f"Pull recommended coding model {report.recommendation.model}.",
            )
        )

    docker_check = _find_check(report, "docker")
    qdrant_check = _find_check(report, "qdrant")
    docker = (
        runner.which("docker")
        if docker_check is not None and docker_check.state is CheckState.HEALTHY
        else None
    )
    if docker is not None and qdrant_check is not None and qdrant_check.state is CheckState.STOPPED:
        actions.append(
            SetupAction(
                SetupActionKind.START_QDRANT,
                "Start the managed Qdrant service.",
                (
                    str(docker),
                    "compose",
                    "--project-name",
                    "repo-intel",
                    "--file",
                    str(setup.compose_file),
                    "up",
                    "--detach",
                    "qdrant",
                ),
                timeout_seconds=_QDRANT_TIMEOUT_SECONDS,
                stream=True,
            )
        )
    return tuple(actions)


def execute_setup_action(
    action: SetupAction,
    runner: CommandRunner,
) -> SetupActionResult:
    """Execute exactly one action that the caller has already approved."""
    try:
        result = runner.run(
            action.args,
            timeout_seconds=action.timeout_seconds,
            env=action.env,
            stream=action.stream,
        )
    except OSError as error:
        raise RepoIntelError(
            "A required setup executable is no longer available.",
            ExitCode.DEPENDENCY,
            hint="Run repo-intel doctor, repair the missing dependency, and try again.",
        ) from error
    if result.returncode != 0 or result.timed_out:
        raise RepoIntelError(
            "The approved setup action did not complete.",
            ExitCode.EXTERNAL_SERVICE,
            hint="Run repo-intel doctor for current service guidance, then try again.",
        )
    return SetupActionResult(action.kind, succeeded=True)


__all__ = ["execute_setup_action", "plan_setup_actions"]
