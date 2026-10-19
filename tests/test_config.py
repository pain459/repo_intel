"""Configuration tests."""
import pytest

from repo_intel.config import Settings, _cached_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear cached settings so each test reads fresh defaults."""
    _cached_settings.cache_clear()


def test_settings_defaults(monkeypatch):
    # Remove env vars that override defaults
    for var in ("HOST", "PORT"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.profile in ("local", "remote-ollama")


def test_repo_root_paths():
    s = Settings(repo_roots="/a,/b")
    assert s.repo_root_paths == ["/a", "/b"]


def test_repo_root_paths_empty():
    s = Settings(repo_roots="")
    assert s.repo_root_paths == []
