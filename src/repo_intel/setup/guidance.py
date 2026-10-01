"""Fixed platform-specific installation guidance."""

from repo_intel.platform import PlatformKind

_GUIDANCE: dict[PlatformKind, dict[str, str]] = {
    PlatformKind.MACOS: {
        "git": "Install Git with Xcode Command Line Tools: xcode-select --install.",
        "rg": "Install ripgrep on macOS with Homebrew: brew install ripgrep.",
        "ollama": "Install Ollama for macOS from https://ollama.com/download.",
        "docker": (
            "Install Docker Desktop for macOS from "
            "https://docs.docker.com/desktop/setup/install/mac-install/."
        ),
    },
    PlatformKind.UBUNTU: {
        "git": "Install Git on Ubuntu: sudo apt-get install git.",
        "rg": "Install ripgrep on Ubuntu: sudo apt-get install ripgrep.",
        "ollama": "Install Ollama for Linux from https://ollama.com/download.",
        "docker": (
            "Install Docker Engine and the Compose plugin using Docker's Ubuntu instructions: "
            "https://docs.docker.com/engine/install/ubuntu/."
        ),
    },
}


def installation_guidance(platform: PlatformKind, dependency: str) -> str:
    """Return guidance without invoking a package manager or installer."""
    return _GUIDANCE[platform].get(
        dependency,
        f"Install {dependency} for {platform.value} and run doctor again.",
    )


__all__ = ["installation_guidance"]
