import sys
from importlib import metadata
from importlib.resources import files

import repo_intel


def test_distribution_version_matches_package_version() -> None:
    assert repo_intel.__version__ == metadata.version("repo-intel")


def test_supported_python_floor() -> None:
    assert sys.version_info >= (3, 12)


def test_qdrant_compose_template_is_packaged() -> None:
    resource = files("repo_intel.setup.resources").joinpath("qdrant.compose.yaml")

    assert resource.is_file()
    assert "__QDRANT_DATA_DIR__" in resource.read_text(encoding="utf-8")
