import pytest


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (
        "KLEGAL_ENV_FILE",
        "KORCOUNSEL_ADMIN_ID",
        "KORCOUNSEL_ADMIN_PASSWORD",
        "KORCOUNSEL_DEV_EDITOR_ID",
        "KORCOUNSEL_DEV_EDITOR_PASSWORD",
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "LAW_OPEN_API_OC",
        "LAW_GO_KR_OC",
        "DATA_DIR",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
