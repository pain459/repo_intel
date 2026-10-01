"""Ubuntu and XDG application-directory conventions."""

from collections.abc import Mapping
from pathlib import Path

from repo_intel.platform.base import AppPaths, PlatformKind


def _xdg_root(environ: Mapping[str, str], name: str, default: Path) -> Path:
    configured = environ.get(name)
    return Path(configured) if configured else default


class UbuntuPlatform:
    """Compute repo_intel paths on Ubuntu."""

    kind = PlatformKind.UBUNTU

    def paths(self, *, home: Path, environ: Mapping[str, str]) -> AppPaths:
        config_root = _xdg_root(environ, "XDG_CONFIG_HOME", home / ".config")
        data_root = _xdg_root(environ, "XDG_DATA_HOME", home / ".local" / "share")
        cache_root = _xdg_root(environ, "XDG_CACHE_HOME", home / ".cache")
        state_root = _xdg_root(environ, "XDG_STATE_HOME", home / ".local" / "state")
        return AppPaths(
            config_dir=config_root / "repo-intel",
            data_dir=data_root / "repo-intel",
            cache_dir=cache_root / "repo-intel",
            log_dir=state_root / "repo-intel" / "log",
        )

