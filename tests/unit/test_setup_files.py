import tomllib
from pathlib import Path

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.setup import files as setup_files
from repo_intel.setup.files import prepare_setup_files, setup_paths


def _app_paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "Application Root with spaces" / "配置"
    return AppPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        log_dir=root / "logs",
    )


def test_setup_paths_are_derived_from_platform_owned_roots(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)

    paths = setup_paths(app_paths)

    assert paths.user_config == app_paths.config_dir / "config.toml"
    assert paths.compose_file == app_paths.config_dir / "qdrant.compose.yaml"
    assert paths.qdrant_data_dir == app_paths.data_dir / "qdrant"
    assert not app_paths.config_dir.exists()


def test_first_preparation_creates_valid_files_and_platform_directories(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)

    prepared = prepare_setup_files(app_paths)

    assert prepared.changed_paths == (
        prepared.paths.user_config,
        prepared.paths.compose_file,
    )
    assert tomllib.loads(prepared.paths.user_config.read_text(encoding="utf-8")) == {}
    compose = prepared.paths.compose_file.read_text(encoding="utf-8")
    assert "qdrant/qdrant:v1.19.1" in compose
    assert '"127.0.0.1:6333:6333"' in compose
    assert '"127.0.0.1:6334:6334"' in compose
    assert 'restart: "no"' in compose
    assert f'source: "{prepared.paths.qdrant_data_dir}"' in compose
    assert prepared.paths.qdrant_data_dir.is_dir()
    assert app_paths.cache_dir.is_dir()
    assert app_paths.log_dir.is_dir()


def test_existing_user_config_is_preserved_byte_for_byte(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)
    paths = setup_paths(app_paths)
    paths.user_config.parent.mkdir(parents=True)
    custom = b'log_level = "DEBUG"\n# user-authored\n'
    paths.user_config.write_bytes(custom)

    prepared = prepare_setup_files(app_paths)

    assert paths.user_config.read_bytes() == custom
    assert paths.user_config not in prepared.changed_paths


def test_second_preparation_makes_no_changes(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)
    first = prepare_setup_files(app_paths)
    config_before = first.paths.user_config.read_bytes()
    compose_before = first.paths.compose_file.read_bytes()

    second = prepare_setup_files(app_paths)

    assert second.changed_paths == ()
    assert second.paths.user_config.read_bytes() == config_before
    assert second.paths.compose_file.read_bytes() == compose_before


def test_stale_managed_compose_file_is_replaced(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)
    paths = setup_paths(app_paths)
    paths.compose_file.parent.mkdir(parents=True)
    paths.compose_file.write_text("stale\n", encoding="utf-8")

    prepared = prepare_setup_files(app_paths)

    assert prepared.changed_paths == (paths.user_config, paths.compose_file)
    assert paths.compose_file.read_text(encoding="utf-8") != "stale\n"


def test_failed_atomic_replace_preserves_existing_managed_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_paths = _app_paths(tmp_path)
    paths = setup_paths(app_paths)
    paths.user_config.parent.mkdir(parents=True)
    paths.user_config.write_text("# existing\n", encoding="utf-8")
    paths.compose_file.write_text("stale\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("private filesystem detail")

    monkeypatch.setattr(setup_files, "_replace", fail_replace)

    with pytest.raises(RepoIntelError) as raised:
        prepare_setup_files(app_paths)

    assert raised.value.exit_code is ExitCode.DATA
    assert "private filesystem detail" not in str(raised.value)
    assert paths.compose_file.read_text(encoding="utf-8") == "stale\n"
    assert list(paths.compose_file.parent.glob("*.tmp")) == []
