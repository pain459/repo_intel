from pathlib import Path

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import (
    MacOSPlatform,
    PlatformKind,
    UbuntuPlatform,
    detect_platform,
)


def test_macos_paths_follow_native_conventions() -> None:
    platform = MacOSPlatform()

    paths = platform.paths(home=Path("/Users/Test User"), environ={})

    assert paths.config_dir == Path(
        "/Users/Test User/Library/Application Support/repo-intel/config"
    )
    assert paths.data_dir == Path("/Users/Test User/Library/Application Support/repo-intel/data")
    assert paths.cache_dir == Path("/Users/Test User/Library/Caches/repo-intel")
    assert paths.log_dir == Path("/Users/Test User/Library/Logs/repo-intel")


def test_macos_paths_preserve_unicode_without_creating_directories(tmp_path: Path) -> None:
    home = tmp_path / "Rävik User"

    paths = MacOSPlatform().paths(home=home, environ={})

    assert "Rävik User" in str(paths.data_dir)
    assert not home.exists()


def test_ubuntu_paths_honor_xdg_overrides() -> None:
    paths = UbuntuPlatform().paths(
        home=Path("/home/ignored"),
        environ={
            "XDG_CONFIG_HOME": "/mnt/config root",
            "XDG_DATA_HOME": "/mnt/data root",
            "XDG_CACHE_HOME": "/mnt/cache root",
            "XDG_STATE_HOME": "/mnt/state root",
        },
    )

    assert paths.config_dir == Path("/mnt/config root/repo-intel")
    assert paths.data_dir == Path("/mnt/data root/repo-intel")
    assert paths.cache_dir == Path("/mnt/cache root/repo-intel")
    assert paths.log_dir == Path("/mnt/state root/repo-intel/log")


def test_ubuntu_paths_use_xdg_defaults() -> None:
    home = Path("/home/test user")

    paths = UbuntuPlatform().paths(home=home, environ={})

    assert paths.config_dir == Path("/home/test user/.config/repo-intel")
    assert paths.data_dir == Path("/home/test user/.local/share/repo-intel")
    assert paths.cache_dir == Path("/home/test user/.cache/repo-intel")
    assert paths.log_dir == Path("/home/test user/.local/state/repo-intel/log")


def test_detect_platform_selects_macos() -> None:
    platform = detect_platform(system="Darwin")

    assert platform.kind is PlatformKind.MACOS


def test_detect_platform_selects_ubuntu_from_injected_os_release() -> None:
    platform = detect_platform(system="Linux", os_release={"ID": "ubuntu"})

    assert platform.kind is PlatformKind.UBUNTU


@pytest.mark.parametrize(
    ("system", "os_release"),
    [
        ("Linux", {"ID": "fedora"}),
        ("Linux", {}),
        ("Windows", {}),
    ],
)
def test_detect_platform_rejects_unsupported_systems(
    system: str,
    os_release: dict[str, str],
) -> None:
    with pytest.raises(RepoIntelError) as raised:
        detect_platform(system=system, os_release=os_release)

    assert raised.value.exit_code is ExitCode.PLATFORM
    assert raised.value.hint is not None
    assert "macOS and Ubuntu" in raised.value.hint
