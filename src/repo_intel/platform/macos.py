"""macOS application-directory conventions."""

from collections.abc import Mapping
from pathlib import Path

from repo_intel.platform.base import AppPaths, PlatformKind


class MacOSPlatform:
    """Compute repo_intel paths on macOS."""

    kind = PlatformKind.MACOS

    def paths(self, *, home: Path, environ: Mapping[str, str]) -> AppPaths:
        del environ
        application_support = home / "Library" / "Application Support" / "repo-intel"
        return AppPaths(
            config_dir=application_support / "config",
            data_dir=application_support / "data",
            cache_dir=home / "Library" / "Caches" / "repo-intel",
            log_dir=home / "Library" / "Logs" / "repo-intel",
        )

