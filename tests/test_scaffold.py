from pathlib import Path

from agent_taskboard import PHASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "agent_taskboard" / "static"


def test_health_is_ready(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["phase"] == PHASE == "ready"
    assert "token" not in response.json()


def test_page_is_static_and_has_no_task_controls(client):
    page = client.get("/")
    assert page.status_code == 200
    text = page.text.lower()
    assert "goals, expected deliverables and latest progress" in text
    assert "<script src=" in text
    assert "run" not in page.text.lower().split("search")[0]
    for name in ("board.js", "board.css", "index.html"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "innerHTML" not in source
        assert "insertAdjacentHTML" not in source
        assert "document.write" not in source
    script = client.get("/static/board.js")
    assert script.status_code == 200
    assert "EventSource" in script.text
    assert "ticket !== generation" in script.text
    assert "textContent" in script.text
