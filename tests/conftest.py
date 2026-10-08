import pytest
from fastapi.testclient import TestClient

from agent_taskboard.app import create_app
from agent_taskboard.config import Settings

WRITER = "test-writer-token"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8765,
        db_path=str(tmp_path / "board.sqlite3"),
        token=WRITER,
        cors_origins=[],
        allowed_artifact_roots=[],
        stale_after_seconds=1800,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {WRITER}"}
