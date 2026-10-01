import io
import logging

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.log import configure_logging


def test_exit_codes_are_stable_for_cli_callers() -> None:
    assert {name: member.value for name, member in ExitCode.__members__.items()} == {
        "SUCCESS": 0,
        "INTERNAL": 1,
        "USAGE": 2,
        "CONFIG": 3,
        "PLATFORM": 4,
        "DEPENDENCY": 5,
        "DATA": 6,
        "EXTERNAL_SERVICE": 7,
    }


def test_repo_intel_error_retains_safe_presentation_fields() -> None:
    error = RepoIntelError(
        "Configuration is invalid",
        ExitCode.CONFIG,
        hint="Check the configuration file",
    )

    assert str(error) == "Configuration is invalid"
    assert error.message == "Configuration is invalid"
    assert error.exit_code is ExitCode.CONFIG
    assert error.hint == "Check the configuration file"


def test_configure_logging_is_idempotent() -> None:
    stream = io.StringIO()

    configure_logging("INFO", stream=stream)
    configure_logging("DEBUG", stream=stream)

    logger = logging.getLogger("repo_intel")
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_configure_logging_rejects_unknown_level() -> None:
    with pytest.raises(RepoIntelError) as raised:
        configure_logging("VERBOSE")

    assert raised.value.exit_code is ExitCode.CONFIG
    assert "VERBOSE" in raised.value.message
