import pytest


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (
        "KLEGAL_ENV_FILE",
        "DATABASE_URL",
        "LAW_OPEN_API_OC",
        "LAW_GO_KR_OC",
        "DATA_DIR",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
