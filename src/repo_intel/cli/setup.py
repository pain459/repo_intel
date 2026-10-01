"""User-facing setup command with per-action consent."""

import os
from pathlib import Path

import typer

from repo_intel.cli.doctor import build_doctor_report
from repo_intel.errors import RepoIntelError
from repo_intel.platform import AppPaths, detect_platform
from repo_intel.runtime import CommandRunner, SubprocessCommandRunner
from repo_intel.setup.actions import execute_setup_action, plan_setup_actions
from repo_intel.setup.files import prepare_setup_files
from repo_intel.setup.models import SetupAction, SetupActionKind


def resolve_app_paths() -> AppPaths:
    """Resolve platform paths without creating them."""
    adapter = detect_platform()
    return adapter.paths(home=Path.home(), environ=os.environ)


def new_command_runner() -> CommandRunner:
    return SubprocessCommandRunner()


def _render_typed_error(error: RepoIntelError) -> None:
    typer.echo(f"Error: {error.message}")
    if error.hint is not None:
        typer.echo(f"Guidance: {error.hint}")


def _explicitly_approved(
    action: SetupAction,
    *,
    pull_embedding: bool,
    pull_qwen: bool,
    start_qdrant: bool,
) -> bool:
    return {
        SetupActionKind.PULL_EMBEDDING: pull_embedding,
        SetupActionKind.PULL_QWEN: pull_qwen,
        SetupActionKind.START_QDRANT: start_qdrant,
    }[action.kind]


def setup_command(
    pull_embedding: bool = typer.Option(
        False,
        "--pull-embedding",
        help="Explicitly approve pulling nomic-embed-text when needed.",
    ),
    pull_qwen: bool = typer.Option(
        False,
        "--pull-qwen",
        help="Explicitly approve pulling the recommended Qwen model when needed.",
    ),
    start_qdrant: bool = typer.Option(
        False,
        "--start-qdrant",
        help="Explicitly approve starting the managed Qdrant service when needed.",
    ),
    no_input: bool = typer.Option(
        False,
        "--no-input",
        help="Decline every unapproved action without prompting.",
    ),
) -> None:
    """Prepare local files and offer individually confirmed external actions."""
    try:
        initial_report = build_doctor_report()
        prepared = prepare_setup_files(resolve_app_paths())
        command_runner = new_command_runner()
        actions = plan_setup_actions(initial_report, prepared.paths, command_runner)

        if prepared.changed_paths:
            for path in prepared.changed_paths:
                typer.echo(f"Prepared local file: {path}")
        else:
            typer.echo("Local setup files are already current.")

        if not actions:
            typer.echo("No external setup actions are needed.")
        else:
            for action in actions:
                typer.echo(f"Proposed: {action.description}")

        skipped = False
        cancelled = False
        for action in actions:
            approved = _explicitly_approved(
                action,
                pull_embedding=pull_embedding,
                pull_qwen=pull_qwen,
                start_qdrant=start_qdrant,
            )
            if not approved and no_input:
                skipped = True
                continue
            if not approved:
                try:
                    approved = typer.confirm(f"{action.description} Proceed?", default=False)
                except (typer.Abort, EOFError):
                    cancelled = True
                    skipped = True
                    break
            if approved:
                execute_setup_action(action, command_runner)
                typer.echo(f"Completed: {action.description}")
            else:
                skipped = True

        if cancelled:
            typer.echo("Setup confirmation cancelled; remaining actions were skipped.")
        elif skipped:
            typer.echo("Skipped unapproved setup actions.")

        final_report = build_doctor_report()
        typer.echo(f"Final diagnostic status: {final_report.exit_code.name.lower()}")
        if final_report.exit_code:
            typer.echo("Run repo-intel doctor for remaining guidance.")
    except RepoIntelError as error:
        _render_typed_error(error)
        raise typer.Exit(code=int(error.exit_code)) from error


__all__ = ["new_command_runner", "resolve_app_paths", "setup_command"]
