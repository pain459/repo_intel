"""PATH-based executable diagnostics."""

from repo_intel.diagnostics.models import CheckState, DiagnosticCheck
from repo_intel.runtime import CommandRunner


def check_executable(
    name: str,
    runner: CommandRunner,
    guidance: str,
) -> DiagnosticCheck:
    """Report whether an executable is discoverable without exposing its path."""
    if runner.which(name) is None:
        return DiagnosticCheck(
            name,
            CheckState.MISSING,
            f"{name} is missing.",
            required=True,
            guidance=guidance,
        )
    return DiagnosticCheck(
        name,
        CheckState.INSTALLED,
        f"{name} is installed.",
        required=True,
    )


__all__ = ["check_executable"]
