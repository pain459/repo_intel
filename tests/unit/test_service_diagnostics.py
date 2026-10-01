from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.diagnostics.models import CheckState
from repo_intel.diagnostics.services import (
    OLLAMA_TAGS_URL,
    QDRANT_HEALTH_URL,
    check_docker,
    check_model,
    check_ollama,
    check_qdrant,
)
from repo_intel.runtime import CommandResult, HttpState, JsonResponse


class StubRunner:
    def __init__(
        self,
        *,
        executables: Mapping[str, Path] | None = None,
        result: CommandResult | None = None,
    ) -> None:
        self.executables = dict(executables or {})
        self.result = result
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
        if self.result is None:
            raise AssertionError(f"unexpected command: {command}")
        return self.result


class StubHttp:
    def __init__(self, response: JsonResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, *, timeout_seconds: float) -> JsonResponse:
        self.calls.append((url, timeout_seconds))
        return self.response


def test_missing_ollama_does_not_probe_http() -> None:
    http = StubHttp(JsonResponse(HttpState.OK, 200, {"models": []}))

    result = check_ollama(StubRunner(), http, guidance="Install Ollama.")

    assert result.check.state is CheckState.MISSING
    assert result.models == ()
    assert http.calls == []


@pytest.mark.parametrize("state", [HttpState.UNREACHABLE, HttpState.TIMEOUT])
def test_unreachable_ollama_is_stopped(state: HttpState) -> None:
    http = StubHttp(JsonResponse(state, None, None))
    runner = StubRunner(executables={"ollama": Path("/opt/Ollama App/ollama")})

    result = check_ollama(runner, http, guidance="Install Ollama.")

    assert result.check.state is CheckState.STOPPED
    assert result.models == ()
    assert http.calls == [(OLLAMA_TAGS_URL, 2.0)]


@pytest.mark.parametrize(
    "response",
    [
        JsonResponse(HttpState.HTTP_ERROR, 503, None),
        JsonResponse(HttpState.TOO_LARGE, 200, None),
        JsonResponse(HttpState.INVALID_JSON, 200, None),
        JsonResponse(HttpState.OK, 200, []),
        JsonResponse(HttpState.OK, 200, {"models": "not-a-list"}),
        JsonResponse(HttpState.OK, 200, {"models": [{"name": 42}]}),
    ],
)
def test_invalid_ollama_response_is_unhealthy(response: JsonResponse) -> None:
    result = check_ollama(
        StubRunner(executables={"ollama": Path("/usr/local/bin/ollama")}),
        StubHttp(response),
        guidance="Install Ollama.",
    )

    assert result.check.state is CheckState.UNHEALTHY
    assert result.models == ()
    assert "not-a-list" not in repr(result)


def test_valid_ollama_response_returns_model_names() -> None:
    payload = {
        "models": [
            {"name": "nomic-embed-text:latest", "size": 123},
            {"name": "qwen2.5-coder:7b", "size": 456},
        ]
    }

    result = check_ollama(
        StubRunner(executables={"ollama": Path("/usr/local/bin/ollama")}),
        StubHttp(JsonResponse(HttpState.OK, 200, payload)),
        guidance="Install Ollama.",
    )

    assert result.check.state is CheckState.HEALTHY
    assert result.models == ("nomic-embed-text:latest", "qwen2.5-coder:7b")


def test_model_check_accepts_only_exact_or_implicit_latest_tag() -> None:
    models = (
        "nomic-embed-text:latest",
        "nomic-embed-text-extra:latest",
        "qwen2.5-coder:7b-instruct",
    )

    embedding = check_model("nomic-embed-text", models, required=True)
    qwen = check_model("qwen2.5-coder:7b", models, required=False)

    assert embedding.state is CheckState.INSTALLED
    assert embedding.required is True
    assert qwen.state is CheckState.MISSING
    assert qwen.required is False


def test_healthy_docker_daemon_uses_discovered_executable() -> None:
    command = ("/Applications/Docker App/docker", "info", "--format", "{{.ServerVersion}}")
    runner = StubRunner(
        executables={"docker": Path("/Applications/Docker App/docker")},
        result=CommandResult(command, 0, "28.0", ""),
    )

    check = check_docker(runner, guidance="Install Docker.")

    assert check.state is CheckState.HEALTHY
    assert runner.calls == [command]


@pytest.mark.parametrize(
    "message",
    [
        "Cannot connect to the Docker daemon at unix:///private.sock",
        "Is the docker daemon running? secret endpoint",
    ],
)
def test_recognized_docker_daemon_failure_is_stopped_without_leaking(message: str) -> None:
    runner = StubRunner(
        executables={"docker": Path("/usr/bin/docker")},
        result=CommandResult(("docker",), 1, "", message),
    )

    check = check_docker(runner, guidance="Start Docker.")

    assert check.state is CheckState.STOPPED
    assert "private" not in repr(check)
    assert "secret" not in repr(check)


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(("docker",), 1, "private-output", "permission denied"),
        CommandResult(("docker",), 124, "", "", timed_out=True),
    ],
)
def test_other_docker_failures_are_unhealthy_without_leaking(result: CommandResult) -> None:
    check = check_docker(
        StubRunner(executables={"docker": Path("/usr/bin/docker")}, result=result),
        guidance="Repair Docker.",
    )

    assert check.state is CheckState.UNHEALTHY
    assert "private-output" not in repr(check)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (JsonResponse(HttpState.INVALID_JSON, 200, None), CheckState.HEALTHY),
        (JsonResponse(HttpState.UNREACHABLE, None, None), CheckState.STOPPED),
        (JsonResponse(HttpState.TIMEOUT, None, None), CheckState.STOPPED),
        (JsonResponse(HttpState.HTTP_ERROR, 503, None), CheckState.UNHEALTHY),
    ],
)
def test_qdrant_health_states(response: JsonResponse, expected: CheckState) -> None:
    http = StubHttp(response)

    check = check_qdrant(http, guidance="Start Qdrant.")

    assert check.state is expected
    assert http.calls == [(QDRANT_HEALTH_URL, 2.0)]
