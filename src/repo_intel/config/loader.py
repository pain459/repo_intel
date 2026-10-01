"""Merge configuration sources with explicit precedence."""

from collections.abc import Mapping
import os
from pathlib import Path
import tomllib
from typing import Any

from pydantic import ValidationError

from repo_intel.config.models import AppConfig
from repo_intel.errors import ExitCode, RepoIntelError


_ENVIRONMENT_FIELDS = {
    "REPO_INTEL_LOG_LEVEL": "log_level",
    "REPO_INTEL_CONTEXT_TOKEN_BUDGET": "context_token_budget",
}


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RepoIntelError(
            f"Invalid configuration file: {path}",
            ExitCode.CONFIG,
            hint="Correct the TOML syntax and try again.",
        ) from error


def _environment_values(environ: Mapping[str, str]) -> dict[str, str]:
    unknown = sorted(
        name
        for name in environ
        if name.startswith("REPO_INTEL_") and name not in _ENVIRONMENT_FIELDS
    )
    if unknown:
        raise RepoIntelError(
            f"Unknown configuration setting: {unknown[0]}",
            ExitCode.CONFIG,
            hint="Remove the unsupported environment variable.",
        )
    return {
        field: environ[name]
        for name, field in _ENVIRONMENT_FIELDS.items()
        if name in environ
    }


def _validation_error(error: ValidationError) -> RepoIntelError:
    first = error.errors(include_input=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    return RepoIntelError(
        f"Invalid configuration setting: {location}",
        ExitCode.CONFIG,
        hint="Correct the setting and try again.",
    )


def load_config(
    *,
    user_file: Path | None = None,
    repository_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> AppConfig:
    """Resolve configuration from lowest to highest precedence."""
    values: dict[str, Any] = {}
    values.update(_read_toml(user_file))
    values.update(_read_toml(repository_file))
    values.update(_environment_values(os.environ if environ is None else environ))
    if cli_overrides:
        values.update({key: value for key, value in cli_overrides.items() if value is not None})

    try:
        return AppConfig.model_validate(values)
    except ValidationError as error:
        raise _validation_error(error) from error
