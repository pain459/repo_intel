"""User-facing project lifecycle commands."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.projects.cleanup import CleanupPlan, CleanupResult
from repo_intel.projects.composition import build_project_commands
from repo_intel.projects.models import ProjectStatus

projects_app = typer.Typer(
    help="List and relocate registered repositories.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _render_typed_error(error: RepoIntelError, *, path_recovery: bool = False) -> None:
    typer.echo(f"Error: {error.message}")
    if error.hint is not None:
        typer.echo(f"Guidance: {error.hint}")
    if path_recovery:
        typer.echo("Guidance: Use --project-id for a moved, missing, or reused repository path.")


def _render_status(status: ProjectStatus) -> None:
    typer.echo(f"Project ID: {status.project.repository_id}")
    typer.echo(f"Name: {status.project.display_name}")
    typer.echo(f"Root: {status.project.canonical_root}")
    typer.echo(f"Lifecycle: {status.project.lifecycle.value}")
    typer.echo(f"Availability: {status.availability.value}")
    typer.echo(f"Data: {status.paths.data_dir}")
    typer.echo(f"Cache: {status.paths.cache_dir}")
    typer.echo(f"Logs: {status.paths.log_dir}")
    if not status.cleanup:
        typer.echo("Cleanup: none")
    else:
        for item in status.cleanup:
            suffix = f" ({item.error_summary})" if item.error_summary is not None else ""
            typer.echo(f"Cleanup: {item.provider_name}={item.state.value}{suffix}")


def _render_plan(plan: CleanupPlan) -> None:
    typer.echo(f"Removal plan for project {plan.project.repository_id}:")
    for resource in plan.resources:
        typer.echo(f"Provider: {resource.provider_name}")
        typer.echo(f"Kind: {resource.kind}")
        typer.echo(f"Identifier: {resource.identifier}")
        typer.echo(f"Exists: {'yes' if resource.exists else 'no'}")
        typer.echo(f"Action: {resource.action}")
    if plan.completed_provider_names:
        typer.echo(f"Already completed: {', '.join(plan.completed_provider_names)}")


def _render_cleanup_result(result: CleanupResult) -> None:
    if result.completed_provider_names:
        typer.echo(f"Completed providers: {', '.join(result.completed_provider_names)}")
    for failure in result.failures:
        typer.echo(f"Failed provider {failure.provider_name}: {failure.summary}")
        if failure.hint is not None:
            typer.echo(f"Guidance: {failure.hint}")
    typer.echo("Project removed." if result.removed_registration else "Project cleanup incomplete.")


def init_command(
    path: Annotated[
        Path | None,
        typer.Argument(help="Repository path; defaults to the current directory."),
    ] = None,
) -> None:
    """Register a Git repository and provision generated storage."""

    try:
        status = build_project_commands().service.init(Path.cwd() if path is None else path)
        _render_status(status)
    except RepoIntelError as error:
        _render_typed_error(error)
        raise typer.Exit(code=int(error.exit_code)) from error


@projects_app.callback(invoke_without_command=True)
def projects_command(context: typer.Context) -> None:
    """List registered repositories when no subcommand is supplied."""

    if context.invoked_subcommand is not None:
        return
    try:
        projects = build_project_commands().service.projects()
        if not projects:
            typer.echo("No registered projects.")
            return
        for index, status in enumerate(projects):
            if index:
                typer.echo("")
            _render_status(status)
    except RepoIntelError as error:
        _render_typed_error(error)
        raise typer.Exit(code=int(error.exit_code)) from error


@projects_app.command("relocate")
def relocate_command(
    repository_id: Annotated[UUID, typer.Argument(help="Registered project UUID.")],
    new_path: Annotated[Path, typer.Argument(help="New repository path.")],
) -> None:
    """Refresh an active registration after its repository moves."""

    try:
        status = build_project_commands().service.relocate(repository_id, new_path)
        _render_status(status)
    except RepoIntelError as error:
        _render_typed_error(error)
        raise typer.Exit(code=int(error.exit_code)) from error


def status_command(
    path: Annotated[
        Path | None,
        typer.Argument(help="Repository path; defaults to the current directory."),
    ] = None,
    project_id: Annotated[
        UUID | None,
        typer.Option("--project-id", help="Select a registered project by UUID."),
    ] = None,
) -> None:
    """Show lifecycle, availability, allocations, and cleanup progress."""

    selected_path = Path.cwd() if path is None and project_id is None else path
    try:
        status = build_project_commands().service.status(
            path=selected_path,
            repository_id=project_id,
        )
        _render_status(status)
    except RepoIntelError as error:
        _render_typed_error(error, path_recovery=project_id is None)
        raise typer.Exit(code=int(error.exit_code)) from error


def remove_command(
    path: Annotated[
        Path | None,
        typer.Argument(help="Repository path; defaults to the current directory."),
    ] = None,
    project_id: Annotated[
        UUID | None,
        typer.Option("--project-id", help="Select a registered project by UUID."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the cleanup plan without changing state."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip confirmation without skipping safety checks."),
    ] = False,
) -> None:
    """Remove generated project resources and its registry entry."""

    if dry_run and force:
        error = RepoIntelError(
            "--dry-run and --force cannot be used together.",
            ExitCode.USAGE,
            "Choose a preview or a confirmed removal.",
        )
        _render_typed_error(error)
        raise typer.Exit(code=int(error.exit_code))

    selected_path = Path.cwd() if path is None and project_id is None else path
    try:
        commands = build_project_commands()
        project = commands.service.resolve_selector(
            path=selected_path,
            repository_id=project_id,
        )
        plan = commands.cleanup.plan(project)
        _render_plan(plan)
        if dry_run:
            return
        if not force:
            try:
                approved = typer.confirm("Proceed with project removal?", default=False)
            except (typer.Abort, EOFError):
                typer.echo("Removal cancelled")
                return
            if not approved:
                typer.echo("Removal cancelled")
                return
        result = commands.cleanup.remove(project)
        _render_cleanup_result(result)
        if result.exit_code is not ExitCode.SUCCESS:
            raise typer.Exit(code=int(result.exit_code))
    except RepoIntelError as error:
        _render_typed_error(error, path_recovery=project_id is None)
        raise typer.Exit(code=int(error.exit_code)) from error


__all__ = [
    "init_command",
    "projects_app",
    "relocate_command",
    "remove_command",
    "status_command",
]
