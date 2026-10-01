"""Idempotent creation of platform-native setup files."""

import json
import os
import tempfile
from importlib.resources import files
from pathlib import Path

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.setup.models import PreparedSetup, SetupPaths

_USER_CONFIG = b"# repo_intel user configuration\n"
_COMPOSE_RESOURCE_PACKAGE = "repo_intel.setup.resources"
_COMPOSE_RESOURCE_NAME = "qdrant.compose.yaml"
_DATA_PLACEHOLDER = "__QDRANT_DATA_DIR__"
_replace = os.replace


def setup_paths(app_paths: AppPaths) -> SetupPaths:
    """Map platform roots to the files managed by setup without creating them."""
    return SetupPaths(
        user_config=app_paths.config_dir / "config.toml",
        compose_file=app_paths.config_dir / "qdrant.compose.yaml",
        qdrant_data_dir=app_paths.data_dir / "qdrant",
    )


def _data_error() -> RepoIntelError:
    return RepoIntelError(
        "Unable to prepare repo_intel application files.",
        ExitCode.DATA,
        hint="Check permissions for the platform application directories and try again.",
    )


def _create_user_config(path: Path) -> bool:
    try:
        with path.open("xb") as stream:
            stream.write(_USER_CONFIG)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return False
    except OSError as error:
        raise _data_error() from error
    return True


def _atomic_write(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise _data_error() from error


def _render_compose(paths: SetupPaths) -> bytes:
    template = (
        files(_COMPOSE_RESOURCE_PACKAGE)
        .joinpath(_COMPOSE_RESOURCE_NAME)
        .read_text(encoding="utf-8")
    )
    quoted_data_path = json.dumps(str(paths.qdrant_data_dir), ensure_ascii=False)
    return template.replace(_DATA_PLACEHOLDER, quoted_data_path).encode()


def prepare_setup_files(app_paths: AppPaths) -> PreparedSetup:
    """Prepare user configuration and the managed Compose service idempotently."""
    paths = setup_paths(app_paths)
    try:
        for directory in (
            app_paths.config_dir,
            app_paths.data_dir,
            app_paths.cache_dir,
            app_paths.log_dir,
            paths.qdrant_data_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _data_error() from error

    changed: list[Path] = []
    if _create_user_config(paths.user_config):
        changed.append(paths.user_config)

    compose = _render_compose(paths)
    try:
        current_compose = paths.compose_file.read_bytes()
    except FileNotFoundError:
        current_compose = None
    except OSError as error:
        raise _data_error() from error
    if current_compose != compose:
        _atomic_write(paths.compose_file, compose)
        changed.append(paths.compose_file)

    return PreparedSetup(paths, tuple(changed))


__all__ = ["prepare_setup_files", "setup_paths"]
