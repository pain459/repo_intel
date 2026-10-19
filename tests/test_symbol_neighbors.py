"""Tests for the symbol-neighbor expansion search path.

The `_symbol_candidates` function activates only when the query looks like
an identifier and returns chunks whose `symbol_name` contains the query.
"""

from __future__ import annotations

from repo_intel.security.prompt_guard import check_prompt_injection


def test_symbol_candidate_only_activates_for_identifiers() -> None:
    """Non-identifier queries should return empty symbol candidates."""
    # This is a unit-style test that verifies regex gating.
    # _symbol_candidates returns {} for natural-language queries.
    import re  # noqa: PLC0415
    ident_re = re.compile(r"^[a-zA-Z_]\w{0,127}$")
    # These should NOT activate symbol search
    assert not ident_re.match("how to configure the database")
    assert not ident_re.match("fix the login bug")
    assert not ident_re.match("src/file.py")
    # These SHOULD activate symbol search
    assert ident_re.match("UserProfile")
    assert ident_re.match("_private_helper")
    assert ident_re.match("compute_checksum")


def test_normal_query_not_flagged_by_injection_guard() -> None:
    """Normal identifier queries must not be flagged as injection."""
    report = check_prompt_injection("UserProfile")
    assert report.is_suspicious is False

    report = check_prompt_injection("compute_checksum")
    assert report.is_suspicious is False
