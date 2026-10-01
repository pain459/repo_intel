import subprocess
import sys

from typer.testing import CliRunner

import repo_intel
from repo_intel.cli.app import app

runner = CliRunner()


def test_help_lists_version_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Repository intelligence" in result.stdout
    assert "version" in result.stdout


def test_version_command_prints_distribution_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == repo_intel.__version__


def test_module_entry_point_has_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "repo_intel", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Repository intelligence" in result.stdout
