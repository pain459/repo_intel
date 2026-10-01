"""Configuration value models."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, PositiveInt


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AppConfig(BaseModel):
    """Resolved application settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    log_level: LogLevel = LogLevel.INFO
    context_token_budget: PositiveInt = 10_000
