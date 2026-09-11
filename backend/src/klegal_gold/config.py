"""Explicit environment loading; credentials are never rendered."""

import logging
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Safe configuration failure for operator-facing output."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3] / "data")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    legacy_parquet_path: Path | None = None
    web_origin: str = "http://127.0.0.1:5173"
    korcounsel_admin_id: str | None = None
    korcounsel_admin_password: SecretStr | None = None
    korcounsel_dev_editor_id: str | None = None
    korcounsel_dev_editor_password: SecretStr | None = None
    law_open_api_oc: SecretStr | None = None
    law_go_kr_oc: SecretStr | None = None

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.database_url is None and any(
            item is not None
            for item in (self.postgres_user, self.postgres_password, self.postgres_db)
        ):
            if (
                not self.postgres_user
                or not self.postgres_db
                or self.postgres_password is None
                or not self.postgres_password.get_secret_value()
            ):
                raise ValueError(
                    "POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB are required together"
                )
            self.database_url = SecretStr(
                make_conninfo(
                    host=self.postgres_host,
                    port=self.postgres_port,
                    user=self.postgres_user,
                    password=self.postgres_password.get_secret_value(),
                    dbname=self.postgres_db,
                )
            )
        origin = urlsplit(self.web_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or (
                origin.scheme == "http" and origin.hostname not in {"127.0.0.1", "localhost", "::1"}
            )
        ):
            raise ValueError("WEB_ORIGIN must be an HTTPS origin or HTTP loopback origin")
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
