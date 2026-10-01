import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from repo_intel.runtime.commands import SubprocessCommandRunner


def test_which_returns_the_exact_discovered_path() -> None:
    runner = SubprocessCommandRunner(
        which_fn=lambda name: "/Applications/Tool Box/bin/rg" if name == "rg" else None
    )

    assert runner.which("rg") == Path("/Applications/Tool Box/bin/rg")
    assert runner.which("missing") is None


def test_run_preserves_arguments_and_merges_an_isolated_environment() -> None:
    calls: list[dict[str, Any]] = []
    original_environment = {"PATH": "/base/bin", "UNCHANGED": "yes"}

    def fake_run(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": tuple(args), **kwargs})
        return subprocess.CompletedProcess(args, 0, "done", "")

    runner = SubprocessCommandRunner(run_fn=fake_run, environ=original_environment)

    result = runner.run(
        ["/Applications/Tool Box/bin/rg", "needle with spaces"],
        timeout_seconds=3,
        env={"ACTION": "approved"},
    )

    assert result.args == ("/Applications/Tool Box/bin/rg", "needle with spaces")
    assert result.stdout == "done"
    assert calls == [
        {
            "args": ("/Applications/Tool Box/bin/rg", "needle with spaces"),
            "check": False,
            "capture_output": True,
            "env": {
                "ACTION": "approved",
                "PATH": "/base/bin",
                "UNCHANGED": "yes",
            },
            "shell": False,
            "text": True,
            "timeout": 3,
        }
    ]
    assert original_environment == {"PATH": "/base/bin", "UNCHANGED": "yes"}


def test_timeout_becomes_a_nonraising_result_without_captured_content() -> None:
    def timed_out(
        args: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="secret-output")

    result = SubprocessCommandRunner(run_fn=timed_out).run(
        ["ollama", "pull", "nomic-embed-text"],
        timeout_seconds=1,
    )

    assert result.returncode == 124
    assert result.timed_out is True
    assert result.stdout == ""
    assert result.stderr == ""
    assert "secret-output" not in repr(result)


def test_streaming_does_not_retain_output() -> None:
    received: list[Mapping[str, object]] = []

    def fake_run(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        received.append(kwargs)
        return subprocess.CompletedProcess(args, 0, None, None)

    result = SubprocessCommandRunner(run_fn=fake_run).run(
        ["ollama", "pull", "nomic-embed-text"],
        timeout_seconds=3_600,
        stream=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
    assert received[0]["capture_output"] is False
