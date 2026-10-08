from pathlib import Path

from fastapi.testclient import TestClient

from agent_taskboard import PHASE
from agent_taskboard.app import PHASE_HEADER, create_app
from agent_taskboard.config import Settings

TOKEN = "replace-with-a-long-random-token"

REGISTER = {
    "title": "Example notes for Alice",
    "task": "Prepare a short example note. Do not include private material.",
    "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
    "group_id": "group_example",
}


def test_import_and_phase():
    import agent_taskboard

    assert agent_taskboard.PHASE == "scaffold"
    assert agent_taskboard.__version__ == "0.1.0"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == PHASE
    assert body["status"] == "ok"
    assert body["service"] == "agent-taskboard"
    assert "token" not in body
    assert "db_path" not in body
    assert response.headers[PHASE_HEADER] == "scaffold"


def test_writes_require_token_then_501(client, settings):
    missing = client.put("/tasks/job_example_alpha", json=REGISTER)
    assert missing.status_code == 401
    assert missing.json()["code"] == "unauthorized"
    wrong = client.put(
        "/tasks/job_example_alpha",
        json=REGISTER,
        headers={"Authorization": "Bearer wrong-token-value"},
    )
    assert wrong.status_code == 401
    saved = client.put(
        "/tasks/job_example_alpha",
        json=REGISTER,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert saved.status_code == 501
    assert saved.json()["code"] == "not_implemented"
    assert "store" in saved.json()["message"]
    assert not Path(settings.db_path).exists()


def test_reads_do_not_require_token_and_do_not_store(client, settings):
    listed = client.get("/tasks")
    assert listed.status_code == 501
    events = client.get("/events")
    assert events.status_code == 501
    artifact = client.get("/artifacts/art_example_alpha")
    assert artifact.status_code == 501
    assert not Path(settings.db_path).exists()


def test_sqlite_connect_is_not_used(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("sqlite connect")

    monkeypatch.setattr("sqlite3.connect", boom)
    assert client.get("/health").status_code == 200
    assert client.get("/tasks").status_code == 501


def test_validation_does_not_echo_values(client):
    response = client.patch(
        "/tasks/job_example_alpha",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "expected_revision": 1,
            "report_key": "report_example_1",
            "result_refs": [{"kind": "http", "value": "javascript:alert(1)", "label": "bad"}],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "javascript:alert(1)" not in response.text


def test_placeholder_page_has_no_token_or_script(client):
    runtime = "runtime-token-not-for-pages"
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8765,
            db_path="./data/agent_taskboard.sqlite3",
            token=runtime,
            cors_origins=[],
            allowed_artifact_roots=[],
        )
    )
    page = TestClient(app).get("/?q=<script>alert(1)</script>")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    text = page.text
    assert "scaffold" in text.lower()
    assert "does not show live tasks" in text.lower()
    assert "<script" not in text.lower()
    assert "<form" not in text.lower()
    assert runtime not in text
    assert TOKEN not in text
    assert "Not started" in text
    assert "In progress" in text
    assert "Done" in text
    assert "javascript:" not in text.lower()
    policy = page.headers["content-security-policy"]
    assert "default-src 'none'" in policy
