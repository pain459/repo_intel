"""Read-only checks for local services and Ollama models."""

from dataclasses import dataclass, field

from repo_intel.diagnostics.dependencies import check_executable
from repo_intel.diagnostics.models import CheckState, DiagnosticCheck
from repo_intel.runtime import CommandRunner, HttpState, JsonHttpClient

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
QDRANT_HEALTH_URL = "http://127.0.0.1:6333/healthz"
_HTTP_TIMEOUT_SECONDS = 2.0
_DOCKER_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class OllamaDiagnostic:
    """Ollama health plus the safely parsed installed model names."""

    check: DiagnosticCheck
    models: tuple[str, ...] = field(repr=False)


def _fixed_check(
    name: str,
    state: CheckState,
    summary: str,
    *,
    required: bool = True,
    guidance: str | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(name, state, summary, required, guidance)


def check_ollama(
    runner: CommandRunner,
    http: JsonHttpClient,
    *,
    guidance: str,
) -> OllamaDiagnostic:
    """Check Ollama availability and parse only model names from its tags response."""
    executable = check_executable("ollama", runner, guidance)
    if executable.state is CheckState.MISSING:
        return OllamaDiagnostic(executable, ())

    response = http.get(OLLAMA_TAGS_URL, timeout_seconds=_HTTP_TIMEOUT_SECONDS)
    if response.state in {HttpState.UNREACHABLE, HttpState.TIMEOUT}:
        return OllamaDiagnostic(
            _fixed_check(
                "ollama",
                CheckState.STOPPED,
                "Ollama is installed but stopped.",
                guidance="Start Ollama and run doctor again.",
            ),
            (),
        )
    if response.state is not HttpState.OK:
        return OllamaDiagnostic(
            _fixed_check(
                "ollama",
                CheckState.UNHEALTHY,
                "Ollama returned an unhealthy response.",
                guidance="Check Ollama logs and run doctor again.",
            ),
            (),
        )

    payload = response.payload
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return _unhealthy_ollama()
    models: list[str] = []
    for item in payload["models"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return _unhealthy_ollama()
        name = item["name"].strip()
        if not name:
            return _unhealthy_ollama()
        models.append(name)

    return OllamaDiagnostic(
        _fixed_check("ollama", CheckState.HEALTHY, "Ollama is healthy."),
        tuple(models),
    )


def _unhealthy_ollama() -> OllamaDiagnostic:
    return OllamaDiagnostic(
        _fixed_check(
            "ollama",
            CheckState.UNHEALTHY,
            "Ollama returned a malformed response.",
            guidance="Update or restart Ollama and run doctor again.",
        ),
        (),
    )


def check_model(
    requested: str,
    installed: tuple[str, ...],
    *,
    required: bool,
) -> DiagnosticCheck:
    """Check an Ollama model tag without prefix or version ambiguity."""
    accepted = {requested}
    if ":" not in requested:
        accepted.add(f"{requested}:latest")
    if accepted.intersection(installed):
        return _fixed_check(
            requested,
            CheckState.INSTALLED,
            f"{requested} is installed.",
            required=required,
        )
    return _fixed_check(
        requested,
        CheckState.MISSING,
        f"{requested} is missing.",
        required=required,
        guidance="Run repo-intel setup to review the model pull.",
    )


def check_docker(runner: CommandRunner, *, guidance: str) -> DiagnosticCheck:
    """Distinguish a missing Docker client, stopped daemon, and unhealthy daemon."""
    docker = runner.which("docker")
    if docker is None:
        return _fixed_check(
            "docker",
            CheckState.MISSING,
            "docker is missing.",
            guidance=guidance,
        )

    result = runner.run(
        [str(docker), "info", "--format", "{{.ServerVersion}}"],
        timeout_seconds=_DOCKER_TIMEOUT_SECONDS,
    )
    if result.returncode == 0 and not result.timed_out:
        return _fixed_check("docker", CheckState.HEALTHY, "Docker is healthy.")

    output = f"{result.stdout}\n{result.stderr}".lower()
    stopped_markers = (
        "cannot connect to the docker daemon",
        "is the docker daemon running",
    )
    if any(marker in output for marker in stopped_markers):
        return _fixed_check(
            "docker",
            CheckState.STOPPED,
            "Docker is installed but stopped.",
            guidance="Start Docker and run doctor again.",
        )
    return _fixed_check(
        "docker",
        CheckState.UNHEALTHY,
        "Docker is unhealthy.",
        guidance="Check Docker access and run doctor again.",
    )


def check_qdrant(http: JsonHttpClient, *, guidance: str) -> DiagnosticCheck:
    """Check the localhost Qdrant health endpoint."""
    response = http.get(QDRANT_HEALTH_URL, timeout_seconds=_HTTP_TIMEOUT_SECONDS)
    plain_text_success = (
        response.state is HttpState.INVALID_JSON
        and response.status_code is not None
        and 200 <= response.status_code < 300
    )
    if response.state is HttpState.OK or plain_text_success:
        return _fixed_check("qdrant", CheckState.HEALTHY, "Qdrant is healthy.")
    if response.state in {HttpState.UNREACHABLE, HttpState.TIMEOUT}:
        return _fixed_check(
            "qdrant",
            CheckState.STOPPED,
            "Qdrant is stopped.",
            guidance=guidance,
        )
    return _fixed_check(
        "qdrant",
        CheckState.UNHEALTHY,
        "Qdrant is unhealthy.",
        guidance="Check the Qdrant container and run doctor again.",
    )


__all__ = [
    "OLLAMA_TAGS_URL",
    "QDRANT_HEALTH_URL",
    "OllamaDiagnostic",
    "check_docker",
    "check_model",
    "check_ollama",
    "check_qdrant",
]
