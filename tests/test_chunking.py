"""Tests for the chunking module."""

import pytest
from repo_intel.indexing.chunker import Chunk, chunk_file, _detect_language


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
