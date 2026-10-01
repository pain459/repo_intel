from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.projects.resolver import resolve_repository
from repo_intel.runtime import CommandResult


class RecordingRunner:
    def __init__(
        self,
        results: Sequence[CommandResult],
        *,
        git_path: Path | None = Path("/usr/bin/git"),
    ) -> None:
        self.results = list(results)
        self.git_path = git_path
        self.which_calls: list[str] = []
        self.run_calls: list[tuple[tuple[str, ...], float]] = []

    def which(self, executable: str) -> Path | None:
        self.which_calls.append(executable)
        return self.git_path

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult:
        assert env is None
        assert stream is False
        self.run_calls.append((tuple(args), timeout_seconds))
        return self.results.pop(0)


def _result(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(("git",), returncode, stdout, stderr)


def _successful_runner(root: Path, git_dir: Path) -> RecordingRunner:
    return RecordingRunner(
        [
            _result("true\n"),
            _result(f"{root}\n"),
            _result(f"{git_dir}\n"),
        ]
    )


@pytest.mark.parametrize("input_kind", ["root", "nested", "spaced-unicode", "symlink"])
def test_resolves_worktree_inputs_to_canonical_root_and_git_identity(
    tmp_path: Path,
    input_kind: str,
) -> None:
    root = tmp_path / "repository"
    if input_kind == "spaced-unicode":
        root = tmp_path / "répository with spaces"
    git_dir = root / ".git"
    nested = root / "src" / "package"
    git_dir.mkdir(parents=True)
    nested.mkdir(parents=True)
    input_path = root if input_kind in {"root", "spaced-unicode"} else nested
    if input_kind == "symlink":
        alias = tmp_path / "repo alias"
        alias.symlink_to(root, target_is_directory=True)
        input_path = alias / "src" / "package"

    canonical_root = root.resolve(strict=True)
    canonical_git_dir = git_dir.resolve(strict=True)
    runner = _successful_runner(canonical_root, canonical_git_dir)

    identity = resolve_repository(input_path, runner)

    assert identity.root == canonical_root
    assert identity.git_dir == canonical_git_dir
    assert (identity.device, identity.inode) == (
        canonical_git_dir.stat().st_dev,
        canonical_git_dir.stat().st_ino,
    )
    assert runner.which_calls == ["git"]
    assert [call[0][-1] for call in runner.run_calls] == [
        "--is-inside-work-tree",
        "--show-toplevel",
        "--absolute-git-dir",
    ]
    assert all(call[0][0] == "/usr/bin/git" for call in runner.run_calls)
    assert all(
        call[0][1:3] == ("-C", str(input_path.resolve(strict=True))) for call in runner.run_calls
    )
    assert all(call[1] == 5.0 for call in runner.run_calls)


def test_missing_git_is_a_dependency_error(tmp_path: Path) -> None:
    runner = RecordingRunner([], git_path=None)

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DEPENDENCY
    assert raised.value.hint is not None


@pytest.mark.parametrize("input_kind", ["missing", "file"])
def test_non_directory_inputs_are_data_errors(tmp_path: Path, input_kind: str) -> None:
    path = tmp_path / input_kind
    if input_kind == "file":
        path.write_text("not a repository")
    runner = RecordingRunner([])

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(path, runner)

    assert raised.value.exit_code is ExitCode.DATA
    assert raised.value.hint is not None
    assert runner.run_calls == []


def test_bare_repository_is_rejected(tmp_path: Path) -> None:
    runner = RecordingRunner([_result("false\n")])

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DATA
    assert raised.value.hint is not None


@pytest.mark.parametrize(
    "result",
    [
        _result(returncode=128),
        _result(returncode=124, stderr="ignored", stdout="ignored"),
        CommandResult(("git",), 124, "ignored", "ignored", timed_out=True),
    ],
    ids=["nonzero", "nonzero-124", "timed-out"],
)
def test_git_command_failures_are_data_errors(tmp_path: Path, result: CommandResult) -> None:
    runner = RecordingRunner([result])

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DATA
    assert raised.value.hint is not None


@pytest.mark.parametrize("output", ["", "maybe\n", "true\nfalse\n"])
def test_worktree_query_requires_one_true_value(tmp_path: Path, output: str) -> None:
    runner = RecordingRunner([_result(output)])

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DATA


@pytest.mark.parametrize(
    ("results", "expected_calls"),
    [
        ([_result("true\n"), _result("")], 2),
        ([_result("true\n"), _result("relative/root\n")], 2),
        ([_result("true\n"), _result("/one\n/two\n")], 2),
        ([_result("true\n"), _result("/missing-root\n")], 2),
    ],
)
def test_malformed_root_output_is_rejected(
    tmp_path: Path,
    results: list[CommandResult],
    expected_calls: int,
) -> None:
    runner = RecordingRunner(results)

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DATA
    assert len(runner.run_calls) == expected_calls


def test_resolved_git_directory_stat_failure_is_a_data_error(tmp_path: Path) -> None:
    root = tmp_path.resolve(strict=True)
    missing_git_dir = tmp_path / "missing-git-dir"
    runner = _successful_runner(root, missing_git_dir)

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    assert raised.value.exit_code is ExitCode.DATA
    assert raised.value.hint is not None


@pytest.mark.parametrize(
    "result",
    [
        _result("SECRET_SENTINEL", returncode=128, stderr="SECRET_SENTINEL"),
        CommandResult(("git",), 124, "SECRET_SENTINEL", "SECRET_SENTINEL", timed_out=True),
    ],
)
def test_git_output_is_never_exposed_in_repository_errors(
    tmp_path: Path,
    result: CommandResult,
) -> None:
    runner = RecordingRunner([result])

    with pytest.raises(RepoIntelError) as raised:
        resolve_repository(tmp_path, runner)

    presented = f"{raised.value.message} {raised.value.hint} {raised.value!r}"
    assert "SECRET_SENTINEL" not in presented
