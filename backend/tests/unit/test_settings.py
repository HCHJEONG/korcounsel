import pytest
from typer.testing import CliRunner

from klegal_gold.cli import app
from klegal_gold.config import ConfigurationError, load_settings


def test_explicit_file_and_environment_precedence(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("LAW_GO_KR_OC=synthetic-file-value\nLOG_LEVEL=WARNING\n")
    monkeypatch.setenv("KLEGAL_ENV_FILE", str(path))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    settings = load_settings()
    assert settings.log_level == "ERROR"
    assert settings.law_api_credential.get_secret_value() == "synthetic-file-value"
    assert "synthetic-file-value" not in repr(settings)


def test_no_implicit_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LAW_OPEN_API_OC=synthetic-unwanted-value\n")
    monkeypatch.chdir(tmp_path)
    assert load_settings().law_api_credential is None
    assert load_settings().data_dir.is_absolute()


def test_alias_conflict_is_safe(monkeypatch):
    monkeypatch.setenv("LAW_OPEN_API_OC", "synthetic-first-secret")
    monkeypatch.setenv("LAW_GO_KR_OC", "synthetic-second-secret")
    result = CliRunner().invoke(app, ["check-config"])
    assert result.exit_code == 1
    assert "secret" not in result.output
    assert "Configuration invalid" in result.output


def test_same_aliases_allowed(monkeypatch):
    monkeypatch.setenv("LAW_OPEN_API_OC", "synthetic-same")
    monkeypatch.setenv("LAW_GO_KR_OC", "synthetic-same")
    assert load_settings().law_api_credential.get_secret_value() == "synthetic-same"


@pytest.mark.parametrize(
    "name,value",
    [("DATA_DIR", "relative"), ("LOG_LEVEL", "INVALID"), ("KLEGAL_ENV_FILE", "/missing/file")],
)
def test_invalid_settings(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        load_settings()
