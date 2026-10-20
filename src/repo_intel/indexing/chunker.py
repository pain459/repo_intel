"""Pure-Python code chunker with language-aware boundaries.

Splits source files into searchable chunks without external dependencies.
Detects function/class/method boundaries using indentation-aware heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from repo_intel.config import get_settings

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
_default = get_settings()
MAX_CHUNK_CHARS = _default.max_file_bytes  # reuse max_file_bytes as upper bound

# Token estimate: 4 chars ≈ 1 token (rough heuristic used by several LLM tools)
CHARS_PER_TOKEN = 4

# Maximum content length per chunk (avoid blowing up context windows)
MAX_CHUNK_LEN = 8_000

# ---------------------------------------------------------------------------
# Language-specific boundary patterns
# ---------------------------------------------------------------------------

# Python: def / class at column 0 or after decorators
# Support async def by allowing optional "async " prefix
_PYTHON_FUNC = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")
_PYTHON_CLASS = re.compile(r"^(\s*)class\s+(\w+)")
_PYTHON_DECORATOR = re.compile(r"^@")

# JavaScript / TypeScript: function / const fn = / class / method
_JS_FUNC = re.compile(
    r"(?:^|[\s;])(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
)
_JS_ARROW = re.compile(
    r"(?:^|[\s;(])(?:export\s+)?(?:const|let|var)\s+(\w+)"
    r"\s*=\s*(?:async\s+)?(?:function|\()",
)
_JS_CLASS = re.compile(r"(?:^|[\s;])class\s+(\w+)")
_JS_METHOD = re.compile(r"^(\s+)(\w+)\s*\(.*\)\s*\{")

# Rust
_RUST_FN = re.compile(r"^(\s*)fn\s+(\w+)\s*[<(]")
_RUST_STRUCT = re.compile(r"^(\s*)(?:pub\s+)?struct\s+(\w+)")
_RUST_IMPL = re.compile(r"^(\s*)impl")

# Go
_GO_FUNC = re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(")
_GO_TYPE = re.compile(r"^type\s+(\w+)\s+(struct|interface)")

# Java / C-style
_JAVA_METHOD = re.compile(
    r"^(\s*)(?:public|private|protected|static|\s)"
    r"*,\s*\w+(?:<[^>]+>)?\s+(\w+)\s*\(",
)
_JAVA_CLASS = re.compile(
    r"^(\s*)(?:public|private|protected)?\s*"
    r"(?:class|interface|enum)\s+(\w+)",
)

# ---------------------------------------------------------------------------
# Chunk data
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A single text chunk extracted from a file."""

    start_line: int  # 1-based
    end_line: int  # 1-based, inclusive
    chunk_type: str  # "function" | "class" | "file" | "doc" | "import"
    symbol_name: str | None
    content: str
    estimated_tokens: int  # rough estimate

    @property
    def content_hash(self) -> str:
        import hashlib

        return hashlib.sha256(self.content.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------

_LANG_PATTERNS: dict[str, tuple] = {
    "python": (_PYTHON_FUNC, _PYTHON_CLASS),
    "javascript": (_JS_FUNC, _JS_ARROW, _JS_CLASS, _JS_METHOD),
    "typescript": (_JS_FUNC, _JS_ARROW, _JS_CLASS, _JS_METHOD),
    "rust": (_RUST_FN, _RUST_STRUCT, _RUST_IMPL),
    "go": (_GO_FUNC, _GO_TYPE),
    "java": (_JAVA_METHOD, _JAVA_CLASS),
    "c": (_JAVA_METHOD, _JAVA_CLASS),
    "cpp": (_JAVA_METHOD, _JAVA_CLASS),
    "ruby": (_PYTHON_FUNC, _PYTHON_CLASS),  # similar indentation-based syntax
}


def _detect_language(relative_path: str) -> str:
    """Guess the programming language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".rb": "ruby",
        ".md": "doc",
        ".rst": "doc",
        ".txt": "doc",
        ".toml": "doc",
        ".yaml": "doc",
        ".yml": "doc",
        ".json": "doc",
        ".xml": "doc",
        ".html": "doc",
        ".css": "doc",
        ".scss": "doc",
        ".sql": "doc",
        ".sh": "doc",
        ".bash": "doc",
        ".zsh": "doc",
        ".dockerfile": "doc",
        ".mk": "doc",
        ".cfg": "doc",
        ".ini": "doc",
        ".env": "doc",
    }
    for ext, lang in ext_map.items():
        if relative_path.lower().endswith(ext):
            return lang
    return ""


def _find_boundaries(lines: list[str], language: str) -> list[tuple[int, int, str, str | None]]:
    """Return (start_line, end_line, kind, name) for each boundary region.

    Lines are 0-indexed here; start/end are inclusive 0-indexed.
    Converted to 1-based at the caller.
    """
    patterns = _LANG_PATTERNS.get(language)
    if not patterns:
        return []

    # Control-flow keywords that should never be indexed as symbols
    _CONTROL_FLOW = frozenset({
        "if", "else", "elif", "for", "while", "switch", "case",
        "try", "catch", "finally", "with", "assert", "return",
        "throw", "await", "yield",
    })

    boundaries: list[tuple[int, int, str, str | None]] = []
    for i, line in enumerate(lines):
        _ = line.rstrip()  # normalize for later use
        for pattern in patterns:
            m = pattern.match(line)
            if not m:
                continued = isinstance(pattern, type(_PYTHON_DECORATOR))
                if continued and _PYTHON_DECORATOR.match(line):
                    continue
                continue
            # Determine name from regex groups
            if m.lastindex and m.lastindex >= 2:
                name = m.group(2)
            elif m.lastindex:
                name = m.group(1)
            else:
                name = None
            if isinstance(name, int):
                name = None
            # Skip control-flow keywords masquerading as symbols
            if name in _CONTROL_FLOW:
                break
            pat_lower = pattern.pattern.lower()
            kind = (
                "function"
                if "func" in pat_lower or "fn" in pat_lower
                or "arrow" in pat_lower or "method" in pat_lower
                or "def\\s" in pat_lower
                else "class"
            )
            # Find the end of the region by looking for the next boundary at same/lower indent
            end = i
            if language == "python":
                base_indent = len(line) - len(line.lstrip())
                j = i + 1
                while j < len(lines):
                    nj = lines[j].rstrip()
                    if nj and len(nj) - len(nj.lstrip()) <= base_indent and not nj.startswith("#"):
                        break
                    end = j
                    j += 1
            else:
                # Brace-based: count open/close braces
                depth = 0
                found_open = False
                j = i
                while j < len(lines):
                    for ch in lines[j]:
                        if ch == "{":
                            depth += 1
                            found_open = True
                        elif ch == "}":
                            depth -= 1
                    if found_open and depth <= 0:
                        end = j
                        break
                    end = j
                    j += 1
            boundaries.append((i, end, kind, name))
            break  # one boundary per line

    return boundaries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_file(file_path: str, content: str) -> list[Chunk]:
    """Split *content* into searchable chunks.

    Parameters
    ----------
    file_path:
        Relative path (used for language detection).
    content:
        Raw file text.
    """
    language = _detect_language(file_path)

    # For documentation files, chunk by headings
    if language == "doc":
        return _chunk_doc(content)

    lines = content.split("\n")

    # Always try boundary detection so that symbols are extractable
    # even from small files (≤ MAX_CHUNK_LEN chars).
    boundaries = _find_boundaries(lines, language)

    # Small files: return as a single chunk.
    # If boundaries were found, emit them as separate symbol chunks
    # so that Symbol records can be created during indexing.
    if len(content) <= MAX_CHUNK_LEN:
        if boundaries:
            return _chunk_by_boundaries(lines, boundaries, language)
        return [
            Chunk(
                start_line=1,
                end_line=len(lines),
                chunk_type="file",
                symbol_name=None,
                content=content,
                estimated_tokens=max(len(content) // CHARS_PER_TOKEN, 1),
            )
        ]

    # Large files: use the boundaries already detected above.
    if boundaries:
        return _chunk_by_boundaries(lines, boundaries, language)

    # Fallback: fixed-size line chunks
    return _chunk_fixed(lines)


def _chunk_by_boundaries(
    lines: list[str],
    boundaries: list[tuple[int, int, str, str | None]],
    language: str,
) -> list[Chunk]:
    """Build chunks from detected boundaries, respecting MAX_CHUNK_LEN."""
    chunks: list[Chunk] = []
    for start, end, kind, name in boundaries:
        chunk_lines = lines[start : end + 1]
        text = "\n".join(chunk_lines)
        if len(text) > MAX_CHUNK_LEN:
            # Recurse: split this region by fixed-size
            sub = _chunk_fixed(chunk_lines)
            for s in sub:
                s.chunk_type = kind
                s.symbol_name = name
                # Adjust line numbers (start is 0-indexed)
                offset = start + 1
                s.start_line += offset
                s.end_line += offset
            chunks.extend(sub)
        else:
            chunks.append(
                Chunk(
                    start_line=start + 1,
                    end_line=end + 1,
                    chunk_type=kind,
                    symbol_name=name,
                    content=text,
                    estimated_tokens=max(len(text) // CHARS_PER_TOKEN, 1),
                )
            )
    return chunks


def _chunk_fixed(lines: list[str]) -> list[Chunk]:
    """Split lines into roughly equal-sized text chunks."""
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    start = 0
    for idx, line in enumerate(lines):
        buf.append(line)
        buf_len += len(line) + 1
        if buf_len >= MAX_CHUNK_LEN and len(buf) > 1:
            text = "\n".join(buf)
            chunks.append(
                Chunk(
                    start_line=start + 1,
                    end_line=idx + 1,
                    chunk_type="file",
                    symbol_name=None,
                    content=text,
                    estimated_tokens=max(len(text) // CHARS_PER_TOKEN, 1),
                )
            )
            buf = []
            buf_len = 0
            start = idx + 1
    if buf:
        text = "\n".join(buf)
        chunks.append(
            Chunk(
                start_line=start + 1,
                end_line=len(lines),
                chunk_type="file",
                symbol_name=None,
                content=text,
                estimated_tokens=max(len(text) // CHARS_PER_TOKEN, 1),
            )
        )
    return chunks


def _chunk_doc(content: str) -> list[Chunk]:
    """Split documentation by Markdown / reST headings."""
    lines = content.split("\n")
    if len(content) <= MAX_CHUNK_LEN:
        return [
            Chunk(
                start_line=1,
                end_line=len(lines),
                chunk_type="doc",
                symbol_name=None,
                content=content,
                estimated_tokens=max(len(content) // CHARS_PER_TOKEN, 1),
            )
        ]
    # Find heading lines: Markdown (#) or reST (==== or ---- underlines)
    heading_re = re.compile(r"^#{1,6}\s+")
    regions: list[tuple[int, int]] = []
    starts: list[int] = [0]
    for i, line in enumerate(lines):
        if heading_re.match(line):
            starts.append(i)
    for j, s in enumerate(starts):
        e = starts[j + 1] - 1 if j + 1 < len(starts) else len(lines) - 1
        regions.append((s, e))
    chunks: list[Chunk] = []
    for s, e in regions:
        region_lines = lines[s : e + 1]
        text = "\n".join(region_lines)
        if len(text) > MAX_CHUNK_LEN:
            sub = _chunk_fixed(region_lines)
            offset = s + 1
            for c in sub:
                c.start_line += offset
                c.end_line += offset
                c.chunk_type = "doc"
            chunks.extend(sub)
        else:
            chunks.append(
                Chunk(
                    start_line=s + 1,
                    end_line=e + 1,
                    chunk_type="doc",
                    symbol_name=None,
                    content=text,
                    estimated_tokens=max(len(text) // CHARS_PER_TOKEN, 1),
                )
            )
    return chunks if chunks else [
        Chunk(
            start_line=1,
            end_line=len(lines),
            chunk_type="doc",
            symbol_name=None,
            content=content,
            estimated_tokens=max(len(content) // CHARS_PER_TOKEN, 1),
        )
    ]
