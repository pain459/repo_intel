"""Typed application settings via pydantic-settings."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Profile & server
    # ------------------------------------------------------------------
    profile: Literal["local", "remote-ollama"] = "remote-ollama"

    host: str = Field(default="127.0.0.1", description="Bind address (loopback by default)")
    port: int = Field(default=8765, ge=1, le=65535)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://repo_intel:CHANGE_ME@postgres:5432/repo_intel",
        description="SQLAlchemy async database URL",
    )

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------
    repo_roots: str = Field(default="/workspace", description="Comma-separated mount paths")

    @property
    def repo_root_paths(self) -> list[str]:
        return [p.strip() for p in self.repo_roots.split(",") if p.strip()]

    # ------------------------------------------------------------------
    # Ollama (inference + embeddings)
    # ------------------------------------------------------------------
    ollama_base_url: str = Field(
        default="http://192.168.68.62:11434", description="Ollama HTTP base URL"
    )

    embedding_model: str = Field(default="nomic-embed-text", description="Embedding model name")
    embedding_batch_size: int = Field(default=16, ge=1)
    ollama_timeout_seconds: int = Field(default=30, ge=1)

    # ------------------------------------------------------------------
    # Indexing (Phase 2+)
    # ------------------------------------------------------------------
    index_poll_seconds: int = Field(
        default=10, ge=1, le=300, description="Working-tree change poll interval"
    )
    max_file_bytes: int = Field(
        default=1_048_576, ge=1024, description="Skip files larger than this many bytes"
    )
    default_context_tokens: int = Field(
        default=12_000, ge=500, description="Default context-pack token budget"
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"


def _setup_json_handler() -> logging.Handler:
    """Return a handler that emits structured JSON log lines."""
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0] is not None:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    return handler


def setup_logging(level: str | None = None) -> None:
    """Configure the root logger from settings."""
    settings = get_settings()
    effective = level or settings.log_level
    log_fmt = settings.log_format

    if log_fmt == "json":
        handler = _setup_json_handler()
        logging.root.setLevel(getattr(logging, effective, logging.INFO))
        logging.root.addHandler(handler)
    else:
        logging.basicConfig(
            level=getattr(logging, effective, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    # Apply credential redaction filter to log output
    from repo_intel.security.log_filter import (  # noqa: PLC0415
        apply_credential_filter,
    )

    apply_credential_filter()


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return _cached_settings()


@lru_cache
def _cached_settings() -> Settings:
    return Settings()
