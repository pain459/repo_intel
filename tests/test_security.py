"""Tests for the security layer: path safety + secret redaction."""

from __future__ import annotations

import os
import pathlib

import pytest

from repo_intel.security.paths import (
    PathTraversalError,
    SecurityConfig,
    is_inside_allowed_root,
    is_safe_relative_path,
    is_secret_file,
    resolve_safe,
)
from repo_intel.security.redaction import redact_content


# ===================================================================
# Path safety tests
# ===================================================================


class TestIsSafeRelativePath:
    def test_normal_paths(self) -> None:
        assert is_safe_relative_path("src/file.py") is True
        assert is_safe_relative_path("a/b/c/d/e.md") is True
        assert is_safe_relative_path("README.md") is True

    def test_reject_parent_traversal(self) -> None:
        assert is_safe_relative_path("../file.py") is False
        assert is_safe_relative_path("src/../../etc/passwd") is False
        assert is_safe_relative_path("a/b/../../../c") is False

    def test_reject_absolute_paths(self) -> None:
        assert is_safe_relative_path("/etc/passwd") is False
        assert is_safe_relative_path("/tmp/foo") is False

    def test_accept_deep_but_valid(self) -> None:
        deep = "a/" * 100 + "file.py"
        assert is_safe_relative_path(deep) is True

    def test_reject_extremely_deep(self) -> None:
        very_deep = "a/" * 201 + "file.py"
        assert is_safe_relative_path(very_deep) is False


class TestResolveSafe:
    def test_basic_resolution(self, tmp_path: pathlib.Path) -> None:
        base = str(tmp_path)
        result = resolve_safe(base, "subdir/file.txt")
        assert result.startswith(os.path.realpath(base))

    def test_reject_traversal_escape(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        base = str(repo_dir)
        with pytest.raises(PathTraversalError):
            resolve_safe(base, "../other_secrets")

    def test_double_dot_in_path(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        base = str(repo_dir)
        with pytest.raises(PathTraversalError):
            resolve_safe(base, "src/../../tmp/malicious")


class TestIsInsideAllowedRoot:
    def test_allowed(self) -> None:
        assert is_inside_allowed_root("/workspace/my-repo/src", ["/workspace"]) is True

    def test_nested_allowed(self) -> None:
        assert is_inside_allowed_root(
            "/workspace/repos/sub/deep", ["/workspace"]
        ) is True

    def test_not_allowed(self) -> None:
        assert is_inside_allowed_root("/etc/shadow", ["/workspace"]) is False

    def test_root_exact_match(self) -> None:
        assert is_inside_allowed_root("/workspace", ["/workspace"]) is True


class TestIsSecretFile:
    def _cfg(self) -> SecurityConfig:
        return SecurityConfig()

    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            "config/.env",
            "id_rsa",
            "id_ed25519",
            ".ssh/id_rsa",
            "secret.key",
            "cert.pem",
            "database.p12",
            "netrc",
            "terraform.tfvars",
        ],
    )
    def test_secret_files_detected(self, path: str) -> None:
        assert is_secret_file(path, self._cfg()) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/main.py",
            "README.md",
            "package.json",
            "Dockerfile",
            "test_file.txt",
            "config.yaml",
        ],
    )
    def test_normal_files_ok(self, path: str) -> None:
        assert is_secret_file(path, self._cfg()) is False


# ===================================================================
# Secret redaction tests
# ===================================================================


class TestRedaction:
    def test_no_secrets_unchanged(self) -> None:
        text = "def hello():\n    print('world')\n"
        result = redact_content(text)
        assert result.patterns_matched == 0
        assert result.cleaned_text == text

    def test_github_token_redacted(self) -> None:
        text = 'GITHUB_TOKEN = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"\n'
        result = redact_content(text)
        assert result.patterns_matched > 0
        assert "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789" not in result.cleaned_text
        assert "***REDACTED***" in result.cleaned_text

    def test_password_assignment_redacted(self) -> None:
        text = "password = 'my_super_secret_password_123'\n"
        result = redact_content(text)
        assert result.patterns_matched > 0
        assert "my_super_secret_password_123" not in result.cleaned_text
        assert "***REDACTED***" in result.cleaned_text

    def test_aws_access_key_redacted(self) -> None:
        text = 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"\n'
        result = redact_content(text)
        assert result.patterns_matched > 0
        assert "AKIAIOSFODNN7EXAMPLE" not in result.cleaned_text

    def test_connection_string_password_redacted(self) -> None:
        text = "DATABASE_URL = postgres://user:p4ssw0rd!complex@host:5432/db\n"
        result = redact_content(text)
        assert result.patterns_matched > 0
        assert "p4ssw0rd!complex" not in result.cleaned_text

    def test_bearer_token_redacted(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123"
        result = redact_content(text)
        assert result.patterns_matched > 0

    def test_private_key_header_redacted(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----"
        result = redact_content(text)
        assert result.patterns_matched > 0
        # The BEGIN header is redacted; END header may remain (that's fine)
        assert "***REDACTED***" in result.cleaned_text
        assert "BEGIN" not in result.cleaned_text

    def test_empty_string(self) -> None:
        result = redact_content("")
        assert result.patterns_matched == 0
        assert result.cleaned_text == ""

    def test_multiline_with_secrets(self) -> None:
        text = (
            "config = {\n"
            "  database_password = 'supersecret_db_pass'\n"
            '  "name": "production-db",\n'
            "}\n"
        )
        result = redact_content(text)
        # The password line should trigger redaction
        assert result.patterns_matched > 0
        # Non-secret value preserved
        assert "production-db" in result.cleaned_text

    def test_pattern_labels_populated(self) -> None:
        text = "password = 'secret123'\n"
        result = redact_content(text)
        assert len(result.pattern_labels) > 0

    def test_no_false_positive_on_normal_strings(self) -> None:
        # These normal strings should NOT trigger redaction
        text = (
            "def calculate_total(items, tax):\n"
            "    total = sum(item.price for item in items)\n"
            "    total += total * tax\n"
            "    return round(total, 2)\n"
        )
        result = redact_content(text)
        assert result.patterns_matched == 0


# ===================================================================
# Integration: discovery + security
# ===================================================================


class TestDiscoverySecurity:
    """End-to-end test: secret files are excluded from discovery."""

    def test_dotenv_excluded(self, tmp_path: pathlib.Path) -> None:
        from repo_intel.indexing.discovery import discover_files

        repo = tmp_path / "test-repo"
        repo.mkdir()

        # Create a .env file (should be excluded)
        (repo / ".env").write_text("SECRET_KEY=test12345\n")
        (repo / "app.py").write_text("print('hello')\n")

        files = discover_files(str(repo))
        rel_paths = [f.relative_path for f in files]
        assert ".env" not in rel_paths
        assert "app.py" in rel_paths

    def test_ssh_dir_excluded(self, tmp_path: pathlib.Path) -> None:
        from repo_intel.indexing.discovery import discover_files

        repo = tmp_path / "test-repo"
        repo.mkdir()
        (repo / ".ssh").mkdir()
        (repo / ".ssh" / "id_rsa").write_text("PRIVATE KEY DATA\n")
        (repo / "main.py").write_text("def run(): pass\n")

        files = discover_files(str(repo))
        rel_paths = [f.relative_path for f in files]
        assert not any(".ssh" in p for p in rel_paths)
        assert "main.py" in rel_paths
