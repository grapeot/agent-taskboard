import pytest

from agent_taskboard.config import load_settings


def _clear(monkeypatch) -> None:
    for key in (
        "AGENT_TASKBOARD_HOST",
        "AGENT_TASKBOARD_PORT",
        "AGENT_TASKBOARD_DB_PATH",
        "AGENT_TASKBOARD_TOKEN",
        "AGENT_TASKBOARD_CORS_ORIGINS",
        "AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS",
        "AGENT_TASKBOARD_STALE_AFTER_SECONDS",
        "AGENT_TASKBOARD_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_missing_token_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear(monkeypatch)
    with pytest.raises(ValueError):
        load_settings()


def test_placeholder_token_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TASKBOARD_TOKEN", "replace-with-a-long-random-token")
    with pytest.raises(ValueError):
        load_settings()


def test_env_file_fills_unset_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear(monkeypatch)
    (tmp_path / ".env").write_text(
        "AGENT_TASKBOARD_TOKEN=test-writer-token\nAGENT_TASKBOARD_PORT=8789\n",
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8789
    assert settings.token == "test-writer-token"
    assert settings.cors_origins == []


def test_cors_star_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TASKBOARD_TOKEN", "test-writer-token")
    monkeypatch.setenv("AGENT_TASKBOARD_CORS_ORIGINS", "*")
    with pytest.raises(ValueError):
        load_settings()
