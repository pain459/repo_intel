from importlib import metadata
import sys

import repo_intel


def test_distribution_version_matches_package_version() -> None:
    assert repo_intel.__version__ == metadata.version("repo-intel")


def test_supported_python_floor() -> None:
    assert sys.version_info >= (3, 12)
