"""Tests for the file discovery module."""

import os
import tempfile

import pytest
from repo_intel.indexing.discovery import discover_files, _detect_language, _is_binary


# ------------------------------------------------------------------
# File discovery
# ------------------------------------------------------------------


class TestFileDiscovery:

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = discover_files(tmpdir)
            assert files == []

    def test_discovers_python_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file
            p = os.path.join(tmpdir, "hello.py")
            with open(p, "w") as f:
                f.write("print('hello')\n")
            files = discover_files(tmpdir)
            assert len(files) >= 1
            rel_paths = [f.relative_path for f in files]
            assert "hello.py" in rel_paths

    def test_skips_binary_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "image.png")
            with open(p, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            files = discover_files(tmpdir)
            for f in files:
                assert f.relative_path != "image.png"

    def test_skips_empty_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "empty.txt")
            with open(p, "w") as f:
                pass
            files = discover_files(tmpdir)
            for f in files:
                assert f.relative_path != "empty.txt"

    def test_file_has_content_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "test.py")
            with open(p, "w") as f:
                f.write("x = 1\n")
            files = discover_files(tmpdir)
            assert len(files) >= 1
            for f in files:
                assert len(f.content_hash) == 64

    def test_file_has_language(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "test.py")
            with open(p, "w") as f:
                f.write("x = 1\n")
            files = discover_files(tmpdir)
            py_files = [f for f in files if f.relative_path == "test.py"]
            if py_files:
                assert py_files[0].language == "python"

    def test_respects_gitignore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create gitignore
            with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
                f.write("*.log\n")
            # Create files
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("x=1\n")
            with open(os.path.join(tmpdir, "debug.log"), "w") as f:
                f.write("debug\n")
            files = discover_files(tmpdir)
            rel_paths = [f.relative_path for f in files]
            assert "debug.log" not in rel_paths
            assert "app.py" in rel_paths


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class TestHelpers:

    def test_detect_language_py(self):
        assert _detect_language("foo.py") == "python"

    def test_detect_language_ts(self):
        assert _detect_language("bar.tsx") == "typescript"

    def test_detect_language_unknown(self):
        assert _detect_language("foo.xyz") == ""

    def test_is_binary_true(self):
        with tempfile.NamedTemporaryFile(suffix=".bin") as f:
            f.write(b"\x00\x01\x02")
            f.flush()
            assert _is_binary(f.name) is True

    def test_is_binary_false(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"hello world\n")
            f.flush()
            assert _is_binary(f.name) is False
