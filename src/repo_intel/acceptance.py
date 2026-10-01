"""Real-machine acceptance support for Modules 1 and 2."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from repo_intel import __version__
from repo_intel.config import load_config
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths, PlatformKind, detect_platform
from repo_intel.runtime import CommandResult, SubprocessCommandRunner
from repo_intel.setup.files import setup_paths

_CHECK_PATTERN = re.compile(
    r"^(.+?): (installed|missing|healthy|stopped|unhealthy) — ",
    re.MULTILINE,
)
_RECOMMENDATION_PREFIX = "Recommended Qwen model: "
_REQUIRED_CHECKS = ("git", "rg", "ollama", "docker", "qdrant", "nomic-embed-text")
_EXPECTED_IMAGE = "qdrant/qdrant:v1.19.1"
_DOCTOR_CODES = {
    int(ExitCode.SUCCESS),
    int(ExitCode.DEPENDENCY),
    int(ExitCode.EXTERNAL_SERVICE),
}

OutputFunction = Callable[[str], None]


class AcceptanceFailure(RuntimeError):
    """A user-facing acceptance-contract failure."""


@dataclass(frozen=True, slots=True)
class DoctorSnapshot:
    """States parsed from one real ``repo-intel doctor`` invocation."""

    checks: dict[str, str]
    recommended_model: str


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes
    modified_ns: int


class _Host:
    """Shell-free command access for the acceptance process."""

    def __init__(self) -> None:
        self.runner = SubprocessCommandRunner()

    def executable(self, name: str) -> Path:
        path = self.runner.which(name)
        if path is None:
            raise AcceptanceFailure(f"required executable is missing from PATH: {name}")
        return path

    def run(
        self,
        args: Sequence[str | Path],
        *,
        allowed_codes: set[int] | None = None,
        timeout_seconds: float = 600,
        stream: bool = False,
        env: Mapping[str, str] | None = None,
        label: str,
    ) -> CommandResult:
        command = tuple(str(arg) for arg in args)
        try:
            result = self.runner.run(
                command,
                timeout_seconds=timeout_seconds,
                stream=stream,
                env=env,
            )
        except OSError as error:
            raise AcceptanceFailure(f"{label} could not start") from error
        accepted = {0} if allowed_codes is None else allowed_codes
        if result.timed_out:
            raise AcceptanceFailure(f"{label} timed out")
        if result.returncode not in accepted:
            raise AcceptanceFailure(
                f"{label} failed with exit code {result.returncode}; rerun it directly for details"
            )
        return result


def parse_doctor_output(output: str) -> DoctorSnapshot:
    """Parse and validate the stable Module 2 doctor surface."""
    checks = dict(_CHECK_PATTERN.findall(output))
    recommendation = next(
        (
            line.removeprefix(_RECOMMENDATION_PREFIX).strip()
            for line in output.splitlines()
            if line.startswith(_RECOMMENDATION_PREFIX)
        ),
        "",
    )
    expected = (*_REQUIRED_CHECKS, recommendation)
    missing = [name for name in expected if not name or name not in checks]
    if missing:
        label = missing[0] if missing[0] else "recommended Qwen model"
        raise AcceptanceFailure(f"doctor output is missing the {label} check")
    return DoctorSnapshot(checks, recommendation)


def validate_compose_contract(compose: str, data_dir: str) -> None:
    """Require the managed service's pinned, local-only storage contract."""
    requirements = (
        (_EXPECTED_IMAGE, "pinned Qdrant image"),
        ('"127.0.0.1:6333:6333"', "localhost REST port"),
        ('"127.0.0.1:6334:6334"', "localhost gRPC port"),
        (f"source: {json.dumps(data_dir, ensure_ascii=False)}", "Qdrant data path"),
    )
    for expected, label in requirements:
        if expected not in compose:
            raise AcceptanceFailure(f"managed Compose file is missing the {label}")


def confirm_action(
    prompt: str,
    *,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """Confirm one live action, defaulting every other response to no."""
    try:
        answer = input_fn(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def assert_no_unapproved_change(
    before: DoctorSnapshot,
    after: DoctorSnapshot,
) -> None:
    """Reject model or service changes made by a declined setup run."""
    protected = ("nomic-embed-text", before.recommended_model, "qdrant")
    for name in protected:
        if before.checks.get(name) != after.checks.get(name):
            raise AcceptanceFailure(f"setup changed {name} without explicit approval")


def _pass(output: OutputFunction, message: str) -> None:
    output(f"[PASS] {message}")


def _section(output: OutputFunction, title: str) -> None:
    output("")
    output(f"=== {title} ===")


def _file_state(path: Path) -> _FileState:
    try:
        return _FileState(path.read_bytes(), path.stat().st_mtime_ns)
    except OSError as error:
        raise AcceptanceFailure(f"cannot inspect required setup file: {path}") from error


def _assert_same_file(path: Path, before: _FileState, label: str) -> None:
    after = _file_state(path)
    if after != before:
        raise AcceptanceFailure(f"{label} changed during an idempotent setup rerun: {path}")


def _run_quality_gate(
    host: _Host,
    uv: Path,
    *,
    output: OutputFunction,
) -> None:
    commands: tuple[tuple[str, tuple[str, ...], float], ...] = (
        ("locked dependency sync", ("sync", "--locked", "--all-groups"), 1_200),
        ("Ruff lint", ("run", "ruff", "check", "."), 600),
        ("Ruff format check", ("run", "ruff", "format", "--check", "."), 600),
        ("strict MyPy", ("run", "mypy", "src/repo_intel", "tests", "scripts"), 600),
        ("complete Pytest suite", ("run", "pytest", "-q"), 1_200),
        ("source and wheel build", ("build",), 600),
    )
    for label, arguments, timeout in commands:
        host.run(
            (uv, *arguments),
            timeout_seconds=timeout,
            stream=True,
            label=label,
        )
        _pass(output, label)


def _run_module_one_contracts(
    host: _Host,
    console: Path,
    *,
    output: OutputFunction,
) -> None:
    help_result = host.run((console, "--help"), label="console help")
    if not all(command in help_result.stdout for command in ("doctor", "setup", "version")):
        raise AcceptanceFailure("console help is missing a public Module 1 or 2 command")
    _pass(output, "console help exposes version, doctor, and setup")

    doctor_help = host.run((console, "doctor", "--help"), label="doctor help")
    doctor_help_text = doctor_help.stdout.lower()
    if "read-only" not in doctor_help_text and "without changing" not in doctor_help_text:
        raise AcceptanceFailure("doctor help does not describe its read-only contract")
    setup_help = host.run((console, "setup", "--help"), label="setup help")
    setup_options = ("--pull-embedding", "--pull-qwen", "--start-qdrant", "--no-input")
    if not all(option in setup_help.stdout for option in setup_options):
        raise AcceptanceFailure("setup help is missing an explicit consent option")
    _pass(output, "doctor and setup help expose safety contracts")

    version = host.run((console, "version"), label="console version")
    if version.stdout.strip() != __version__:
        raise AcceptanceFailure("console version does not match the imported package version")
    _pass(output, f"console version is {__version__}")

    module_help = host.run(
        (sys.executable, "-m", "repo_intel", "--help"),
        label="module entry-point help",
    )
    if "Repository intelligence" not in module_help.stdout:
        raise AcceptanceFailure("python -m repo_intel did not expose the CLI")
    _pass(output, "python -m repo_intel entry point")

    offline_probe = """
import importlib
import socket

def reject(*args, **kwargs):
    raise RuntimeError("network access during import")

socket.create_connection = reject
socket.socket.connect = reject
for name in (
    "repo_intel",
    "repo_intel.cli.app",
    "repo_intel.config",
    "repo_intel.platform",
    "repo_intel.domain",
    "repo_intel.ports",
):
    importlib.import_module(name)
"""
    host.run(
        (sys.executable, "-c", offline_probe),
        label="offline package import",
    )
    _pass(output, "public package imports perform no network access")

    with tempfile.TemporaryDirectory(prefix="repo-intel-config-") as temporary:
        root = Path(temporary)
        user_file = root / "user.toml"
        repository_file = root / "repository.toml"
        user_file.write_text(
            'log_level = "WARNING"\ncontext_token_budget = 1000\n',
            encoding="utf-8",
        )
        repository_file.write_text(
            'log_level = "ERROR"\ncontext_token_budget = 2000\n',
            encoding="utf-8",
        )
        config = load_config(
            user_file=user_file,
            repository_file=repository_file,
            environ={"REPO_INTEL_LOG_LEVEL": "DEBUG"},
            cli_overrides={"context_token_budget": 4000},
        )
        if config.log_level.value != "DEBUG" or config.context_token_budget != 4000:
            raise AcceptanceFailure("configuration precedence is not CLI > environment > files")
    _pass(output, "configuration precedence")

    adapter = detect_platform()
    with tempfile.TemporaryDirectory(prefix="repo-intel-paths-") as temporary:
        home = Path(temporary) / "home"
        if adapter.kind is PlatformKind.MACOS:
            paths = adapter.paths(home=home, environ={})
            expected_root = home / "Library"
        else:
            xdg_root = Path(temporary) / "xdg"
            paths = adapter.paths(
                home=home,
                environ={
                    "XDG_CONFIG_HOME": str(xdg_root / "config"),
                    "XDG_DATA_HOME": str(xdg_root / "data"),
                    "XDG_CACHE_HOME": str(xdg_root / "cache"),
                    "XDG_STATE_HOME": str(xdg_root / "state"),
                },
            )
            expected_root = xdg_root
        if not all(
            path.is_relative_to(expected_root)
            for path in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.log_dir)
        ):
            raise AcceptanceFailure("platform adapter produced a path outside its native roots")
    _pass(output, f"native {adapter.kind.value} application paths")


def _doctor(
    host: _Host,
    console: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[DoctorSnapshot, CommandResult]:
    result = host.run(
        (console, "doctor"),
        allowed_codes=_DOCTOR_CODES,
        timeout_seconds=30,
        env=env,
        label="repo-intel doctor",
    )
    return parse_doctor_output(result.stdout), result


def _prove_doctor_read_only(
    host: _Host,
    console: Path,
    *,
    output: OutputFunction,
) -> DoctorSnapshot:
    with tempfile.TemporaryDirectory(prefix="repo-intel-doctor-") as temporary:
        root = Path(temporary)
        candidates = {
            "HOME": root / "home",
            "XDG_CONFIG_HOME": root / "config",
            "XDG_DATA_HOME": root / "data",
            "XDG_CACHE_HOME": root / "cache",
            "XDG_STATE_HOME": root / "state",
        }
        snapshot, _ = _doctor(
            host,
            console,
            env={name: str(path) for name, path in candidates.items()},
        )
        created = [path for path in candidates.values() if path.exists()]
        if created:
            raise AcceptanceFailure(f"doctor created application state: {created[0]}")
    _pass(output, "doctor is read-only with isolated platform paths")
    return snapshot


def _real_app_paths() -> AppPaths:
    return detect_platform().paths(home=Path.home(), environ=os.environ)


def _run_setup(
    host: _Host,
    console: Path,
    *options: str,
    stream: bool = False,
) -> CommandResult:
    return host.run(
        (console, "setup", "--no-input", *options),
        timeout_seconds=3_900,
        stream=stream,
        label=f"repo-intel setup {' '.join(options)}".rstrip(),
    )


def _require_state(snapshot: DoctorSnapshot, name: str, expected: str) -> None:
    actual = snapshot.checks.get(name)
    if actual != expected:
        raise AcceptanceFailure(
            f"doctor reports {name} as {actual or 'absent'}, expected {expected}; "
            "run repo-intel doctor for guidance and rerun this acceptance test"
        )


def _offer_model_pull(
    host: _Host,
    console: Path,
    snapshot: DoctorSnapshot,
    *,
    model: str,
    option: str,
    description: str,
    input_fn: Callable[[str], str],
    output: OutputFunction,
) -> tuple[DoctorSnapshot, bool]:
    if snapshot.checks[model] == "installed":
        _pass(output, f"{model} is installed")
        return snapshot, False
    if not confirm_action(description, input_fn=input_fn):
        output(f"[SKIP] {model} was not downloaded")
        return snapshot, True
    _run_setup(host, console, option, stream=True)
    updated, _ = _doctor(host, console)
    _require_state(updated, model, "installed")
    _pass(output, f"real Ollama pull installed {model}")
    return updated, False


def _wait_for_qdrant(
    host: _Host,
    console: Path,
    *,
    timeout_seconds: float = 45,
) -> DoctorSnapshot:
    deadline = time.monotonic() + timeout_seconds
    latest, _ = _doctor(host, console)
    while latest.checks["qdrant"] != "healthy" and time.monotonic() < deadline:
        time.sleep(1)
        latest, _ = _doctor(host, console)
    _require_state(latest, "qdrant", "healthy")
    return latest


def _parse_json_object(raw: str, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AcceptanceFailure(f"Docker returned malformed {label} metadata") from error
    if not isinstance(value, dict):
        raise AcceptanceFailure(f"Docker returned unexpected {label} metadata")
    return value


def _parse_json_array(raw: str, label: str) -> list[object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AcceptanceFailure(f"Docker returned malformed {label} metadata") from error
    if not isinstance(value, list):
        raise AcceptanceFailure(f"Docker returned unexpected {label} metadata")
    return value


def _verify_managed_qdrant(
    host: _Host,
    compose_file: Path,
    *,
    output: OutputFunction,
) -> None:
    docker = host.executable("docker")
    compose_prefix = (
        docker,
        "compose",
        "--project-name",
        "repo-intel",
        "--file",
        compose_file,
    )
    container = host.run(
        (*compose_prefix, "ps", "--status", "running", "--quiet", "qdrant"),
        label="managed Qdrant container lookup",
    ).stdout.strip()
    if not container or "\n" in container:
        raise AcceptanceFailure("the healthy Qdrant endpoint is not owned by one managed container")

    image = host.run(
        (docker, "inspect", "--format", "{{.Config.Image}}", container),
        label="managed Qdrant image inspection",
    ).stdout.strip()
    if image != _EXPECTED_IMAGE:
        raise AcceptanceFailure(
            f"managed Qdrant uses {image or 'no image'}, expected {_EXPECTED_IMAGE}"
        )

    bindings = _parse_json_object(
        host.run(
            (
                docker,
                "inspect",
                "--format",
                "{{json .HostConfig.PortBindings}}",
                container,
            ),
            label="managed Qdrant port inspection",
        ).stdout,
        "port-binding",
    )
    for container_port, host_port in (("6333/tcp", "6333"), ("6334/tcp", "6334")):
        entries = bindings.get(container_port)
        if not isinstance(entries, list) or not entries:
            raise AcceptanceFailure(f"managed Qdrant is missing port {container_port}")
        if any(
            not isinstance(entry, dict)
            or entry.get("HostIp") != "127.0.0.1"
            or entry.get("HostPort") != host_port
            for entry in entries
        ):
            raise AcceptanceFailure(f"managed Qdrant port {container_port} is not localhost-only")

    mounts = _parse_json_array(
        host.run(
            (docker, "inspect", "--format", "{{json .Mounts}}", container),
            label="managed Qdrant mount inspection",
        ).stdout,
        "mount",
    )
    if not any(
        isinstance(mount, dict)
        and mount.get("Type") == "bind"
        and mount.get("Destination") == "/qdrant/storage"
        for mount in mounts
    ):
        raise AcceptanceFailure("managed Qdrant is missing its storage bind mount")
    _pass(output, "managed Qdrant image, localhost ports, and storage mount")


def _run_module_two_contracts(
    host: _Host,
    console: Path,
    *,
    input_fn: Callable[[str], str],
    output: OutputFunction,
) -> bool:
    baseline = _prove_doctor_read_only(host, console, output=output)

    app_paths = _real_app_paths()
    managed = setup_paths(app_paths)
    original_user_config = (
        _file_state(managed.user_config).content if managed.user_config.is_file() else None
    )

    first_setup = _run_setup(host, console)
    if first_setup.stdout:
        output(first_setup.stdout.rstrip())
    if not managed.user_config.is_file() or not managed.compose_file.is_file():
        raise AcceptanceFailure("setup did not create the required application files")
    config_state = _file_state(managed.user_config)
    compose_state = _file_state(managed.compose_file)
    if original_user_config is not None and config_state.content != original_user_config:
        raise AcceptanceFailure("setup overwrote the existing user configuration")
    try:
        compose_text = compose_state.content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AcceptanceFailure("managed Compose file is not valid UTF-8") from error
    validate_compose_contract(
        compose_text,
        str(managed.qdrant_data_dir),
    )
    _pass(output, "real setup prepared and preserved platform-native files")
    _pass(output, "managed Compose file is pinned and localhost-only")

    snapshot, doctor_result = _doctor(host, console)
    assert_no_unapproved_change(baseline, snapshot)
    _pass(output, "setup --no-input made no unapproved external change")
    output(doctor_result.stdout.rstrip())
    for dependency in ("git", "rg"):
        _require_state(snapshot, dependency, "installed")
    _require_state(snapshot, "ollama", "healthy")
    _require_state(snapshot, "docker", "healthy")
    _pass(output, "real Git, ripgrep, Ollama, and Docker diagnostics")

    skipped = False
    snapshot, action_skipped = _offer_model_pull(
        host,
        console,
        snapshot,
        model="nomic-embed-text",
        option="--pull-embedding",
        description="Pull real nomic-embed-text with Ollama? It will remain installed",
        input_fn=input_fn,
        output=output,
    )
    skipped |= action_skipped

    recommended = snapshot.recommended_model
    snapshot, action_skipped = _offer_model_pull(
        host,
        console,
        snapshot,
        model=recommended,
        option="--pull-qwen",
        description=(
            f"Download the real recommended model {recommended} with Ollama? "
            "The model may be large and will remain installed"
        ),
        input_fn=input_fn,
        output=output,
    )
    skipped |= action_skipped

    qdrant_state = snapshot.checks["qdrant"]
    if qdrant_state == "stopped":
        if confirm_action(
            "Start the real managed Qdrant container? Its data and container will remain",
            input_fn=input_fn,
        ):
            _run_setup(host, console, "--start-qdrant", stream=True)
            snapshot = _wait_for_qdrant(host, console)
            _pass(output, "real managed Qdrant service started and became healthy")
        else:
            output("[SKIP] managed Qdrant was not started")
            skipped = True
    elif qdrant_state == "healthy":
        _pass(output, "Qdrant endpoint is healthy")
    else:
        raise AcceptanceFailure(
            f"Qdrant is {qdrant_state}; run repo-intel doctor for guidance and rerun this test"
        )

    if snapshot.checks["qdrant"] == "healthy":
        _verify_managed_qdrant(host, managed.compose_file, output=output)

    final_snapshot, final_doctor = _doctor(host, console)
    if final_doctor.stdout:
        output(final_doctor.stdout.rstrip())
    if not skipped:
        installed = {
            "git",
            "rg",
            "nomic-embed-text",
            final_snapshot.recommended_model,
        }
        for name in (*_REQUIRED_CHECKS, final_snapshot.recommended_model):
            expected = "installed" if name in installed else "healthy"
            _require_state(final_snapshot, name, expected)
        if final_doctor.returncode != int(ExitCode.SUCCESS):
            raise AcceptanceFailure("final doctor did not return success after complete setup")
        _pass(output, "final doctor reports the complete real environment healthy")

    rerun = _run_setup(host, console)
    if rerun.stdout:
        output(rerun.stdout.rstrip())
    _assert_same_file(managed.user_config, config_state, "user configuration")
    _assert_same_file(managed.compose_file, compose_state, "managed Compose file")
    _pass(output, "setup rerun is file-idempotent")
    if not skipped and "No external setup actions are needed." not in rerun.stdout:
        raise AcceptanceFailure("completed setup still proposes an external action on rerun")
    if not skipped:
        _pass(output, "setup rerun proposes no external actions")
    return skipped


def run_real_acceptance(
    repo_root: Path,
    *,
    input_fn: Callable[[str], str] = input,
    output: OutputFunction = print,
) -> int:
    """Run the complete, mutating Module 1–2 acceptance workflow."""
    if not (repo_root / "pyproject.toml").is_file() or not (repo_root / "uv.lock").is_file():
        raise AcceptanceFailure("run this acceptance test from a repo_intel source checkout")
    os.chdir(repo_root)

    host = _Host()
    uv = host.executable("uv")
    _section(output, "Module 1: foundation and quality gate")
    _run_quality_gate(host, uv, output=output)
    console = host.executable("repo-intel")
    _run_module_one_contracts(host, console, output=output)

    _section(output, "Module 2: real setup and diagnostics")
    skipped = _run_module_two_contracts(
        host,
        console,
        input_fn=input_fn,
        output=output,
    )
    output("")
    if skipped:
        output("ACCEPTANCE INCOMPLETE: one or more real setup actions were declined.")
        return 2
    output("ACCEPTANCE PASSED: Modules 1 and 2 work end to end on this machine.")
    return 0


def acceptance_main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path | None = None,
) -> int:
    """CLI wrapper with explicit disclosure and safe failure rendering."""
    parser = argparse.ArgumentParser(
        description=(
            "Runs the real Module 1–2 acceptance workflow. It downloads real Ollama models, "
            "starts the managed Qdrant service, and leaves successful setup resources in place. "
            "Every download and service start still requires a separate confirmation."
        )
    )
    parser.parse_args(argv)
    try:
        if not confirm_action(
            "Begin the real Module 1–2 acceptance test on this machine?",
        ):
            print("Acceptance test cancelled; no test action was started.")
            return 2
        return run_real_acceptance(
            Path.cwd() if repo_root is None else repo_root,
        )
    except AcceptanceFailure as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    except RepoIntelError as error:
        print(f"[FAIL] {error.message}", file=sys.stderr)
        if error.hint is not None:
            print(f"Guidance: {error.hint}", file=sys.stderr)
        return int(error.exit_code)
    except KeyboardInterrupt:
        print("\nAcceptance test cancelled.", file=sys.stderr)
        return 130


__all__ = [
    "AcceptanceFailure",
    "DoctorSnapshot",
    "acceptance_main",
    "assert_no_unapproved_change",
    "confirm_action",
    "parse_doctor_output",
    "run_real_acceptance",
    "validate_compose_contract",
]
