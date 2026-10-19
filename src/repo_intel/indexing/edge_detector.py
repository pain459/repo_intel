"""Heuristic symbol-edge detection from source text.

Scans import/call/reference patterns to build a lightweight dependency
graph between symbols without a full AST parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RelationType = Literal["imports", "calls", "references"]


@dataclass
class SymbolEdgeRaw:
    from_name: str
    to_name: str
    relation_type: RelationType
    line: int


# Python import patterns
_RE_PY_IMPORT = re.compile(
    r"^from\s+([\w.]+)\s+import\s+([\w.]+)",
)
_RE_PY_IMPORT_AS = re.compile(
    r"^import\s+([\w.]+)\s+as\s+(\w+)",
)
_RE_PY_DIRECT_IMPORT = re.compile(
    r"^import\s+([\w.]+)",
)

# Function call patterns (identifier followed by parenthesis)
_RE_PY_CALL = re.compile(
    r"(\w+)\s*\(",
)

# JS/TS import patterns
_RE_JS_IMPORT = re.compile(
    r"import\s+(?:{[^}]*}|\w+)\s+from\s+['\"]([^'\"]+)['\"]",
)
_RE_JS_REQUIRE = re.compile(
    r"require\s*\(\s*['\"]([^'\"]+)['\"]",
)

# Built-in names that are not interesting calls
_BUILTINS = frozenset({
    "print", "len", "str", "int", "list", "dict", "set", "tuple",
    "float", "bool", "type", "isinstance", "hasattr", "getattr",
    "setattr", "super", "range", "enumerate", "zip", "map",
    "filter", "sorted", "reversed", "open",
})


def detect_edges(
    content: str,
    defined_symbols: set[str] | None = None,
) -> list[SymbolEdgeRaw]:
    """Scan *content* for import/call/reference edges.

    Returns a list of edges between symbols defined in the file.
    """
    if defined_symbols is None:
        defined_symbols = set()

    edges: list[SymbolEdgeRaw] = []
    lines = content.splitlines()

    for line_num, line in enumerate(lines, 1):
        stripped = line.lstrip()

        # Python imports
        m = _RE_PY_IMPORT.match(stripped)
        if m:
            to_sym = m.group(1).split(".")[-1]
            from_sym = m.group(2).split(".")[-1]
            if to_sym in defined_symbols and from_sym in defined_symbols:
                edges.append(SymbolEdgeRaw(
                    from_name=from_sym,
                    to_name=to_sym,
                    relation_type="imports",
                    line=line_num,
                ))
            continue

        m = _RE_PY_IMPORT_AS.match(stripped)
        if m:
            to_sym = m.group(1).split(".")[-1]
            from_sym = m.group(2)
            if to_sym in defined_symbols and from_sym in defined_symbols:
                edges.append(SymbolEdgeRaw(
                    from_name=from_sym,
                    to_name=to_sym,
                    relation_type="imports",
                    line=line_num,
                ))
            continue

        m = _RE_PY_DIRECT_IMPORT.match(stripped)
        if m:
            to_sym = m.group(1).split(".")[-1]
            if to_sym in defined_symbols:
                edges.append(SymbolEdgeRaw(
                    from_name=to_sym,
                    to_name=to_sym,
                    relation_type="imports",
                    line=line_num,
                ))
            continue

        # JS/TS imports
        for m in _RE_JS_IMPORT.finditer(stripped):
            module = m.group(1)
            if module in defined_symbols:
                edges.append(SymbolEdgeRaw(
                    from_name=module,
                    to_name=module,
                    relation_type="imports",
                    line=line_num,
                ))

        for m in _RE_JS_REQUIRE.finditer(stripped):
            module = m.group(1)
            if module in defined_symbols:
                edges.append(SymbolEdgeRaw(
                    from_name=module,
                    to_name=module,
                    relation_type="imports",
                    line=line_num,
                ))

        # Function calls (skip import/class/def/comment lines and built-ins)
        if not stripped.startswith(("import ", "from ", "class ", "def ", "#")):
            for m in _RE_PY_CALL.finditer(stripped):
                caller = m.group(1)
                if (caller in defined_symbols
                        and caller not in _BUILTINS):
                    edges.append(SymbolEdgeRaw(
                        from_name=caller,
                        to_name=caller,
                        relation_type="calls",
                        line=line_num,
                    ))

    # De-duplicate
    seen: set[tuple[str, str, str]] = set()
    unique: list[SymbolEdgeRaw] = []
    for e in edges:
        key = (e.from_name, e.to_name, e.relation_type)
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique
