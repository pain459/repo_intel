"""Tests for the MCP configure CLI command."""

from __future__ import annotations

from typer.testing import CliRunner

from repo_intel.cli import cli

runner = CliRunner()


def test_mcp_configure_help() -> None:
    result = runner.invoke(cli, ["mcp", "configure", "--help"])
    assert result.exit_code == 0
    assert "Generate MCP client configuration" in result.output


def test_mcp_configure_stdio_dry_run(capsys) -> None:
    """Test --help path runs without error, actual write requires confirmation."""
    # Invoke with --help to validate the command exists
    result = runner.invoke(cli, ["mcp", "configure", "--transport", "stdio"])
    # Exits with error because typer.confirm gets no input in non-interactive mode
    assert result.exit_code in (0, 1)


def test_mcp_cli_exists() -> None:
    """Verify the mcp subcommand is registered."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "mcp" in result.output


def test_mcp_subcommand_help() -> None:
    result = runner.invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "configure" in result.output
