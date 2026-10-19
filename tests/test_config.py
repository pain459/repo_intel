"""Configuration tests."""
from repo_intel.config import Settings


def test_settings_defaults():
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
