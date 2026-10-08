import pytest

from agent_taskboard.config import load_settings


def test_defaults_are_loopback(monkeypatch):
    for key in (
        "AGENT_TASKBOARD_HOST",
        "AGENT_TASKBOARD_PORT",
        "AGENT_TASKBOARD_DB_PATH",
        "AGENT_TASKBOARD_TOKEN",
        "AGENT_TASKBOARD_CORS_ORIGINS",
        "AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = load_settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.token == ""
    assert settings.cors_origins == []


def test_cors_star_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_TASKBOARD_CORS_ORIGINS", "*")
    with pytest.raises(ValueError):
        load_settings()
