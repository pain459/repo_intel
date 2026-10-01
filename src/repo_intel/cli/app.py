"""Top-level Typer application."""

import typer

from repo_intel import __version__
from repo_intel.cli.doctor import doctor_command
from repo_intel.cli.projects import init_command, projects_app, remove_command, status_command
from repo_intel.cli.setup import setup_command

app = typer.Typer(
    help="Repository intelligence for local coding agents.",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """Repository intelligence for local coding agents."""


@app.command()
def version() -> None:
    """Print the installed repo_intel version."""
    typer.echo(__version__)


app.command("doctor")(doctor_command)
app.command("init")(init_command)
app.add_typer(projects_app, name="projects")
app.command("remove")(remove_command)
app.command("setup")(setup_command)
app.command("status")(status_command)


def main() -> None:
    """Run the command-line application."""
    app()
