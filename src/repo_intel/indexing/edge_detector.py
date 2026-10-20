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


# Regex to detect function/class/method definitions for scope tracking
_RE_DEF = re.compile(r"^(?:async\s+)?def\s+(\w+)")
_RE_CLASS_DEF = re.compile(r"^class\s+(\w+)")
_RE_TS_FUNC = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)")
_RE_TS_METHOD = re.compile(r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*[:{]")


def detect_edges(
    content: str,
    defined_symbols: set[str] | None = None,
) -> list[SymbolEdgeRaw]:
    """Scan *content* for import/call/reference edges.

    Tracks the enclosing symbol (function/class) scope so that call edges
    use the enclosing symbol as *from_name*, producing real dependency
    relationships instead of self-loops.

    Returns a list of edges between symbols defined in the file.
    """
    if defined_symbols is None:
        defined_symbols = set()

    edges: list[SymbolEdgeRaw] = []
    lines = content.splitlines()

    # Scope stack: tracks the current enclosing symbol(s)
    scope: list[str] = []

    for line_num, line in enumerate(lines, 1):
        stripped = line.lstrip()

        # Track scope entries (def/class at reduced indentation = enter)
        m_def = _RE_DEF.match(stripped)
        if m_def:
            func_name = m_def.group(1)
            scope.append(func_name)
            continue

        m_class = _RE_CLASS_DEF.match(stripped)
        if m_class:
            cls_name = m_class.group(1)
            scope.append(cls_name)
            continue

        # JS/TS function definitions
        m_ts_func = _RE_TS_FUNC.match(stripped)
        if m_ts_func:
            scope.append(m_ts_func.group(1))
            continue

        # JS/TS method definitions
        m_ts_method = _RE_TS_METHOD.match(stripped)
        if m_ts_method:
            scope.append(m_ts_method.group(1))
            continue

        # Python imports — from_name is enclosing scope or module-level
        m = _RE_PY_IMPORT.match(stripped)
        if m:
            to_sym = m.group(1).split(".")[-1]
            from_sym = m.group(2).split(".")[-1]
            if to_sym in defined_symbols and from_sym in defined_symbols:
                enclosing = scope[-1] if scope else from_sym
                edges.append(SymbolEdgeRaw(
                    from_name=enclosing,
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
                enclosing = scope[-1] if scope else from_sym
                edges.append(SymbolEdgeRaw(
                    from_name=enclosing,
                    to_name=to_sym,
                    relation_type="imports",
                    line=line_num,
                ))
            continue

        m = _RE_PY_DIRECT_IMPORT.match(stripped)
        if m:
            to_sym = m.group(1).split(".")[-1]
            if to_sym in defined_symbols:
                enclosing = scope[-1] if scope else to_sym
                edges.append(SymbolEdgeRaw(
                    from_name=enclosing,
                    to_name=to_sym,
                    relation_type="imports",
                    line=line_num,
                ))
            continue

        # JS/TS imports
        for m in _RE_JS_IMPORT.finditer(stripped):
            module = m.group(1)
            if module in defined_symbols:
                enclosing = scope[-1] if scope else module
                edges.append(SymbolEdgeRaw(
                    from_name=enclosing,
                    to_name=module,
                    relation_type="imports",
                    line=line_num,
                ))

        for m in _RE_JS_REQUIRE.finditer(stripped):
            module = m.group(1)
            if module in defined_symbols:
                enclosing = scope[-1] if scope else module
                edges.append(SymbolEdgeRaw(
                    from_name=enclosing,
                    to_name=module,
                    relation_type="imports",
                    line=line_num,
                ))

        # Function calls — use enclosing scope as from_name, callee as to_name
        if not stripped.startswith(("import ", "from ", "class ", "def ", "#")):
            for m in _RE_PY_CALL.finditer(stripped):
                callee = m.group(1)
                if (callee in defined_symbols
                        and callee not in _BUILTINS):
                    enclosing = scope[-1] if scope else callee
                    # Only add if from != to (avoid self-loops)
                    if enclosing != callee:
                        edges.append(SymbolEdgeRaw(
                            from_name=enclosing,
                            to_name=callee,
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
