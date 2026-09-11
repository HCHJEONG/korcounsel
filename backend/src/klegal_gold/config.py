"""Explicit environment loading; credentials are never rendered."""

import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Safe configuration failure for operator-facing output."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3] / "data")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr | None = None
    legacy_parquet_path: Path | None = None
    law_open_api_oc: SecretStr | None = None
    law_go_kr_oc: SecretStr | None = None

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if not self.data_dir.is_absolute():
            raise ValueError("DATA_DIR must be absolute")
        if self.legacy_parquet_path is not None and not self.legacy_parquet_path.is_absolute():
            raise ValueError("LEGACY_PARQUET_PATH must be absolute")
        if self.law_open_api_oc is not None and self.law_go_kr_oc is not None:
            if self.law_open_api_oc.get_secret_value() != self.law_go_kr_oc.get_secret_value():
                raise ValueError("Conflicting API credential aliases")
        return self

    @property
    def law_api_credential(self) -> SecretStr | None:
        return self.law_open_api_oc or self.law_go_kr_oc


def load_settings() -> Settings:
    """Read process environment and only an explicitly chosen environment file."""
    env_file = os.environ.get("KLEGAL_ENV_FILE")
    if env_file and not Path(env_file).is_file():
        raise ConfigurationError("Configured environment file is unavailable")
    try:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except (ValidationError, OSError) as exc:
        raise ConfigurationError("Invalid configuration; check variable names and values") from exc


def configure_logging(settings: Settings) -> None:
    """Configure application logging without printing configuration values."""
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
