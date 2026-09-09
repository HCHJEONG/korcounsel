from fastapi.testclient import TestClient
from typer.testing import CliRunner

from klegal_gold.cli import app
from klegal_gold.web.app import create_app


def test_liveness_without_db_or_credentials():
    with TestClient(create_app()) as client:
        result = client.get("/api/health")
        assert result.status_code == 200
        assert result.json()["service"] == "korcounsel-api"
        assert client.get("/api/cases").status_code == 404


def test_db_check_fails_closed_without_configuration():
    result = CliRunner().invoke(app, ["check-db"])
    assert result.exit_code == 1
    assert result.output.strip() == "Database unavailable"
