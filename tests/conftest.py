import pytest
from fastapi.testclient import TestClient

from agent_taskboard.app import create_app
from agent_taskboard.config import Settings

TOKEN = "replace-with-a-long-random-token"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8765,
        db_path=str(tmp_path / "agent_taskboard.sqlite3"),
        token=TOKEN,
        cors_origins=[],
        allowed_artifact_roots=[],
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
