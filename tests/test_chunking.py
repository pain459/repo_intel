"""Tests for the chunking module."""

from repo_intel.indexing.chunker import (
    _detect_language,
    _find_boundaries,
    chunk_file,
)

# ------------------------------------------------------------------
# Language detection
# ------------------------------------------------------------------


class TestDetectLanguage:
    def test_python(self):
        assert _detect_language("foo/bar.py") == "python"

    def test_typescript(self):
        assert _detect_language("src/index.tsx") == "typescript"

    def test_markdown(self):
        assert _detect_language("README.md") == "doc"

    def test_unknown(self):
        assert _detect_language("data.xyz") == ""


# ------------------------------------------------------------------
# Chunking
# ------------------------------------------------------------------


class TestChunking:
    def test_small_file_single_chunk(self):
        content = "print('hello')\n"
        chunks = chunk_file("test.py", content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "file"
        assert chunks[0].content == content

    def test_chunk_has_line_numbers(self):
        content = "\n".join(f"line {i}" for i in range(50))
        chunks = chunk_file("test.py", content)
        for c in chunks:
            assert c.start_line >= 1
            assert c.end_line >= c.start_line

    def test_chunk_content_hash(self):
        content = "print('hello')\n"
        chunks = chunk_file("test.py", content)
        assert chunks[0].content_hash
        assert len(chunks[0].content_hash) == 64  # SHA-256 hex

    def test_estimated_tokens_positive(self):
        content = "print('hello')\n"
        chunks = chunk_file("test.py", content)
        for c in chunks:
            assert c.estimated_tokens >= 1

    def test_doc_chunking_by_headings(self):
        content = "# Title\n\nBody\n\n## Section 2\n\nMore text\n"
        chunks = chunk_file("README.md", content)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.chunk_type == "doc"

    # ------------------------------------------------------------------
    # Small-file symbol extraction (regression for post-eval investigation)
    # ------------------------------------------------------------------

    def test_small_python_file_extracts_function_symbols(self):
        """Small Python files with function definitions should produce
        chunks with symbol_name set, even when the file is under the
        MAX_CHUNK_LEN threshold."""
        content = (
            "def authenticate(username, password):\n"
            "    return True\n"
            "\n"
            "def login_access_token(request):\n"
            "    return {}\n"
        )
        chunks = chunk_file("auth.py", content)
        symbol_chunks = [c for c in chunks if c.symbol_name is not None]
        assert len(symbol_chunks) >= 2, "Expected both functions to be detected"
        names = {c.symbol_name for c in symbol_chunks}
        assert "authenticate" in names
        assert "login_access_token" in names

    def test_small_python_file_extracts_class_symbols(self):
        """Small Python files with class definitions should produce
        chunks with symbol_name set."""
        content = (
            "class UserRepository:\n"
            "    def find_by_id(self, uid):\n"
            "        pass\n"
        )
        chunks = chunk_file("repo.py", content)
        symbol_chunks = [c for c in chunks if c.symbol_name is not None]
        names = {c.symbol_name for c in symbol_chunks}
        assert "UserRepository" in names

    def test_small_file_without_functions_stays_single_chunk(self):
        """A small file with no detectable boundaries should still
        return a single 'file' chunk."""
        content = "x = 1\ny = 2\nz = x + y\n"
        chunks = chunk_file("math.py", content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "file"
        assert chunks[0].symbol_name is None

    def test_boundary_detection_runs_on_small_files(self):
        """_find_boundaries should detect functions regardless of
        file size."""
        lines = [
            "def foo():",
            "    pass",
            "",
            "def bar():",
            "    return 1",
        ]
        boundaries = _find_boundaries(lines, "python")
        assert len(boundaries) == 2
        names = [b[3] for b in boundaries]
        assert "foo" in names
        assert "bar" in names
