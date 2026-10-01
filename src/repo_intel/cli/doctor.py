"""User-facing read-only doctor command."""

import typer

from repo_intel.diagnostics import DoctorReport, run_doctor
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import detect_platform
from repo_intel.runtime import SubprocessCommandRunner, UrllibJsonHttpClient


def build_doctor_report() -> DoctorReport:
    """Build a production diagnostic snapshot without resolving application paths."""
    platform = detect_platform()
    return run_doctor(
        platform.kind,
        SubprocessCommandRunner(),
        UrllibJsonHttpClient(),
    )


def _render_report(report: DoctorReport) -> None:
    for check in report.checks:
        typer.echo(f"{check.name}: {check.state.value} — {check.summary}")
        if check.guidance is not None:
            typer.echo(f"  Guidance: {check.guidance}")
    typer.echo(f"Recommended Qwen model: {report.recommendation.model}")
    typer.echo(f"Recommendation basis: {report.recommendation.reason}")
    if report.recommendation.uncertain:
        typer.echo("Recommendation confidence: uncertain")


def doctor_command() -> None:
    """Inspect dependencies and services without changing the machine."""
    try:
        report = build_doctor_report()
    except RepoIntelError as error:
        typer.echo(f"Error: {error.message}")
        if error.hint is not None:
            typer.echo(f"Guidance: {error.hint}")
        raise typer.Exit(code=int(error.exit_code)) from error

    _render_report(report)
    if report.exit_code is not ExitCode.SUCCESS:
        raise typer.Exit(code=int(report.exit_code))


__all__ = ["build_doctor_report", "doctor_command"]
