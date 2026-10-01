"""Top-level Typer application."""

import typer

from repo_intel import __version__

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


def main() -> None:
    """Run the command-line application."""
    app()
