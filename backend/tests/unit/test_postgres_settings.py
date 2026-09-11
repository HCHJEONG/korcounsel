import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr, ValidationError

from klegal_gold.config import Settings


def test_individual_postgres_fields_preserve_password_special_characters():
    password = "synthetic 'quote' \\ slash @:? # spaces"
    settings = Settings(
        postgres_host="postgres",
        postgres_port=5432,
        postgres_user="fixture",
        postgres_password=SecretStr(password),
        postgres_db="fixture_db",
    )
    info = conninfo_to_dict(settings.database_url.get_secret_value())
    assert info["password"] == password
    assert info["host"] == "postgres" and info["dbname"] == "fixture_db"
    assert password not in repr(settings)


def test_explicit_database_url_has_precedence():
    settings = Settings(
        database_url=SecretStr("postgresql://fixture@localhost/explicit"),
        postgres_user="other",
        postgres_password=SecretStr("other-fixture"),
        postgres_db="other_db",
    )
    assert conninfo_to_dict(settings.database_url.get_secret_value())["dbname"] == "explicit"


def test_partial_individual_fields_fail_closed():
    with pytest.raises(ValidationError):
        Settings(postgres_user="fixture")


def test_no_database_configuration_remains_optional_for_health():
    assert Settings().database_url is None
