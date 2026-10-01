import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

import repo_intel.project_acceptance as project_acceptance
from repo_intel.platform import AppPaths
from repo_intel.project_acceptance import (
    AcceptanceFailure,
    AcceptanceOutcome,
    assert_protected_files_unchanged,
    capture_protected_files,
    ensure_command_succeeded,
    parse_project_output,
    run_project_acceptance,
    validate_dry_run,
    validate_isolated_app_paths,
)
from repo_intel.runtime import CommandResult

PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _complete_output(root: Path) -> str:
    return f"""\
Project ID: {PROJECT_ID}
Name: repository
Root: {root}
Lifecycle: active
Availability: available
Data: {root}/isolated-data
Cache: {root}/isolated-cache
Logs: {root}/isolated-logs
Cleanup: none
"""


def test_acceptance_help_discloses_temporary_isolation_and_no_host_services() -> None:
    script = Path(__file__).parents[2] / "scripts" / "acceptance_module_03.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    normalized = " ".join(result.stdout.split()).lower()
    assert result.returncode == 0
    assert "temporary repositories" in normalized
    assert "isolated application roots" in normalized
    assert "does not download models" in normalized
    assert "does not use docker or qdrant" in normalized


def test_isolated_paths_reject_any_location_outside_temporary_root(tmp_path: Path) -> None:
    safe = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "cache",
        tmp_path / "logs",
    )
    validate_isolated_app_paths(tmp_path, safe)

    escaped = AppPaths(
        tmp_path / "config",
        tmp_path.parent / "escaped-data",
        tmp_path / "cache",
        tmp_path / "logs",
    )
    with pytest.raises(AcceptanceFailure, match="escapes"):
        validate_isolated_app_paths(tmp_path, escaped)


def test_project_output_parser_requires_uuid_and_every_stable_field(tmp_path: Path) -> None:
    parsed = parse_project_output(_complete_output(tmp_path))

    assert parsed.repository_id == PROJECT_ID
    assert parsed.root == tmp_path
    assert parsed.lifecycle == "active"
    assert parsed.availability == "available"

    for missing_field in ("Project ID", "Root", "Data", "Cache", "Logs"):
        incomplete = "\n".join(
            line
            for line in _complete_output(tmp_path).splitlines()
            if not line.startswith(f"{missing_field}:")
        )
        with pytest.raises(AcceptanceFailure, match="incomplete"):
            parse_project_output(incomplete)


def test_dry_run_requires_every_owned_location_and_matching_provider(tmp_path: Path) -> None:
    parsed = parse_project_output(_complete_output(tmp_path))
    output = f"""\
Removal plan for project {PROJECT_ID}:
Provider: cache
Kind: directory
Identifier: {parsed.paths.cache_dir}
Exists: yes
Action: remove
Provider: data
Kind: directory
Identifier: {parsed.paths.data_dir}
Exists: yes
Action: remove
Provider: logs
Kind: directory
Identifier: {parsed.paths.log_dir}
Exists: yes
Action: remove
"""

    validate_dry_run(output, parsed.paths)

    with pytest.raises(AcceptanceFailure, match="logs"):
        validate_dry_run(
            output.replace(f"Identifier: {parsed.paths.log_dir}\n", ""),
            parsed.paths,
        )


@pytest.mark.parametrize("mutated_name", ["source.py", ".repo-intel.toml", "other.py", "sentinel"])
def test_protected_file_checks_detect_every_mutation(
    tmp_path: Path,
    mutated_name: str,
) -> None:
    names = ("source.py", ".repo-intel.toml", "other.py", "sentinel")
    paths = tuple(tmp_path / name for name in names)
    for path in paths:
        path.write_text(f"original {path.name}")
    before = capture_protected_files(paths)
    (tmp_path / mutated_name).write_text("changed")

    with pytest.raises(AcceptanceFailure, match=mutated_name):
        assert_protected_files_unchanged(before)


def test_failed_stage_is_named_without_echoing_captured_secret() -> None:
    result = CommandResult(
        ("repo-intel", "status"),
        6,
        "SECRET_SENTINEL stdout",
        "SECRET_SENTINEL stderr",
    )

    with pytest.raises(AcceptanceFailure) as raised:
        ensure_command_succeeded(result, "project status")

    assert "project status" in str(raised.value)
    assert "SECRET_SENTINEL" not in str(raised.value)


def test_runner_returns_zero_only_when_final_registry_forgets_every_project(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        project_acceptance,
        "_execute_acceptance",
        lambda output: AcceptanceOutcome(registry_forgotten=False),
    )

    failed = run_project_acceptance([])
    failed_output = capsys.readouterr().out

    assert failed == 1
    assert "final registry verification" in failed_output

    def raise_secret(output: object) -> AcceptanceOutcome:
        del output
        raise RuntimeError("SECRET_UNEXPECTED_FAILURE")

    monkeypatch.setattr(project_acceptance, "_execute_acceptance", raise_secret)
    unexpected = run_project_acceptance([])
    unexpected_output = capsys.readouterr().out

    assert unexpected == 1
    assert "unexpected isolated workflow failure" in unexpected_output
    assert "SECRET_UNEXPECTED_FAILURE" not in unexpected_output

    monkeypatch.setattr(
        project_acceptance,
        "_execute_acceptance",
        lambda output: AcceptanceOutcome(registry_forgotten=True),
    )
    passed = run_project_acceptance([])
    passed_output = capsys.readouterr().out

    assert passed == 0
    assert "MODULE 3 ACCEPTANCE PASSED" in passed_output
