"""Read-only orchestration for the complete diagnostic snapshot."""

from repo_intel.diagnostics.dependencies import check_executable
from repo_intel.diagnostics.models import DoctorReport
from repo_intel.diagnostics.services import (
    check_docker,
    check_model,
    check_ollama,
    check_qdrant,
)
from repo_intel.platform import PlatformKind
from repo_intel.runtime import CommandRunner, JsonHttpClient
from repo_intel.setup.guidance import installation_guidance
from repo_intel.setup.hardware import inspect_hardware
from repo_intel.setup.models import HardwareProfile
from repo_intel.setup.recommendation import recommend_qwen


def run_doctor(
    platform: PlatformKind,
    runner: CommandRunner,
    http: JsonHttpClient,
    *,
    hardware_profile: HardwareProfile | None = None,
) -> DoctorReport:
    """Inspect local dependencies without changing files or processes."""
    hardware = inspect_hardware(platform, runner) if hardware_profile is None else hardware_profile
    recommendation = recommend_qwen(hardware)
    git = check_executable("git", runner, installation_guidance(platform, "git"))
    ripgrep = check_executable("rg", runner, installation_guidance(platform, "rg"))
    ollama = check_ollama(
        runner,
        http,
        guidance=installation_guidance(platform, "ollama"),
    )
    docker = check_docker(runner, guidance=installation_guidance(platform, "docker"))
    qdrant = check_qdrant(
        http,
        guidance="Run repo-intel setup to review Qdrant startup.",
    )
    checks = (
        git,
        ripgrep,
        ollama.check,
        docker,
        qdrant,
        check_model("nomic-embed-text", ollama.models, required=True),
        check_model(recommendation.model, ollama.models, required=False),
    )
    return DoctorReport(checks, hardware, recommendation)


__all__ = ["run_doctor"]
