"""Immutable diagnostic results."""

from dataclasses import dataclass
from enum import StrEnum

from repo_intel.errors import ExitCode
from repo_intel.setup.models import HardwareProfile, ModelRecommendation


class CheckState(StrEnum):
    """Stable dependency and service states shown by doctor."""

    INSTALLED = "installed"
    MISSING = "missing"
    HEALTHY = "healthy"
    STOPPED = "stopped"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One secret-safe diagnostic finding."""

    name: str
    state: CheckState
    summary: str
    required: bool
    guidance: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Complete point-in-time health report."""

    checks: tuple[DiagnosticCheck, ...]
    hardware: HardwareProfile
    recommendation: ModelRecommendation

    @property
    def exit_code(self) -> ExitCode:
        required_states = {check.state for check in self.checks if check.required}
        if required_states & {CheckState.STOPPED, CheckState.UNHEALTHY}:
            return ExitCode.EXTERNAL_SERVICE
        if CheckState.MISSING in required_states:
            return ExitCode.DEPENDENCY
        return ExitCode.SUCCESS


__all__ = ["CheckState", "DiagnosticCheck", "DoctorReport"]
