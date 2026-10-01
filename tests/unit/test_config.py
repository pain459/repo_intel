from pathlib import Path

import pytest
from pydantic import ValidationError

from repo_intel.config import AppConfig, LogLevel, load_config
from repo_intel.errors import ExitCode, RepoIntelError


def write_toml(path: Path, **values: object) -> Path:
    lines = []
    for key, value in values.items():
        if isinstance(value, str):
            rendered = f'"{value}"'
        elif isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = str(value)
        lines.append(f"{key} = {rendered}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_defaults() -> None:
    config = load_config(environ={})

    assert config.log_level is LogLevel.INFO
    assert config.context_token_budget == 10_000


def test_precedence(tmp_path: Path) -> None:
    user = write_toml(
        tmp_path / "user.toml",
        log_level="WARNING",
        context_token_budget=1_000,
    )
    repository = write_toml(
        tmp_path / "repository.toml",
        log_level="ERROR",
        context_token_budget=2_000,
    )

    config = load_config(
        user_file=user,
        repository_file=repository,
        environ={
            "REPO_INTEL_LOG_LEVEL": "DEBUG",
            "REPO_INTEL_CONTEXT_TOKEN_BUDGET": "3000",
        },
        cli_overrides={"context_token_budget": 4_000},
    )

    assert config.log_level is LogLevel.DEBUG
    assert config.context_token_budget == 4_000


def test_missing_optional_files_use_defaults(tmp_path: Path) -> None:
    config = load_config(
        user_file=tmp_path / "missing-user.toml",
        repository_file=tmp_path / "missing-repository.toml",
        environ={},
    )

    assert config == AppConfig()


def test_none_cli_override_does_not_erase_lower_precedence_value(tmp_path: Path) -> None:
    user = write_toml(tmp_path / "user.toml", log_level="WARNING")

    config = load_config(
        user_file=user,
        environ={},
        cli_overrides={"log_level": None},
    )

    assert config.log_level is LogLevel.WARNING


@pytest.mark.parametrize(
    ("values", "invalid_setting"),
    [
        ({"context_token_budget": 0}, "context_token_budget"),
        ({"context_token_budget": -1}, "context_token_budget"),
        ({"log_level": "VERBOSE"}, "log_level"),
        ({"unknown_option": True}, "unknown_option"),
    ],
)
def test_invalid_file_value_is_a_typed_config_error(
    tmp_path: Path,
    values: dict[str, object],
    invalid_setting: str,
) -> None:
    repository = write_toml(tmp_path / "repository.toml", **values)

    with pytest.raises(RepoIntelError) as raised:
        load_config(repository_file=repository, environ={})

    assert raised.value.exit_code is ExitCode.CONFIG
    assert invalid_setting in raised.value.message


def test_malformed_toml_names_the_source_without_echoing_content(tmp_path: Path) -> None:
    repository = tmp_path / "repository.toml"
    repository.write_text('log_level = "DEBUG"\nprivate_value = "do-not-echo', encoding="utf-8")

    with pytest.raises(RepoIntelError) as raised:
        load_config(repository_file=repository, environ={})

    assert raised.value.exit_code is ExitCode.CONFIG
    assert str(repository) in raised.value.message
    assert "do-not-echo" not in raised.value.message


@pytest.mark.parametrize(
    ("environ", "invalid_setting"),
    [
        ({"REPO_INTEL_CONTEXT_TOKEN_BUDGET": "many"}, "context_token_budget"),
        ({"REPO_INTEL_LOG_LEVEL": "VERBOSE"}, "log_level"),
        ({"REPO_INTEL_UNKNOWN_OPTION": "value"}, "REPO_INTEL_UNKNOWN_OPTION"),
    ],
)
def test_invalid_environment_value_is_a_typed_config_error(
    environ: dict[str, str],
    invalid_setting: str,
) -> None:
    with pytest.raises(RepoIntelError) as raised:
        load_config(environ=environ)

    assert raised.value.exit_code is ExitCode.CONFIG
    assert invalid_setting in raised.value.message


def test_app_config_is_immutable() -> None:
    config = AppConfig()

    with pytest.raises(ValidationError):
        config.context_token_budget = 1
