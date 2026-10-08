import socket
import threading
import time

import httpx
import pytest
import uvicorn

from agent_taskboard.app import create_app

pytestmark = pytest.mark.integration


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(settings):
    port = _port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_write_reaches_sse_then_snapshot(live_server, auth):
    body = {
        "title": "Example notes for Alice",
        "task": "Prepare a short example note. Do not include private material.",
        "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
        "group_id": "group_example",
    }
    with httpx.Client(timeout=5) as reader, httpx.Client(timeout=5) as writer:
        with reader.stream("GET", f"{live_server}/events") as stream:
            assert stream.status_code == 200
            lines = stream.iter_lines()
            assert next(lines) == ": ready"
            started = time.perf_counter()
            created = writer.put(f"{live_server}/tasks/job_example_alpha", headers=auth, json=body)
            assert created.status_code == 201
            data = ""
            for line in lines:
                if line.startswith("data: "):
                    data = line
                    break
            assert time.perf_counter() - started < 1
            assert "job_example_alpha" in data
        snapshot = writer.get(f"{live_server}/tasks").json()
        assert snapshot["count"] == 1
        writer.patch(
            f"{live_server}/tasks/job_example_alpha",
            headers=auth,
            json={"expected_revision": 1, "report_key": "report_example_1", "status": "accepted"},
        )
        again = writer.get(f"{live_server}/tasks/job_example_alpha").json()
        assert again["ui_state"] == "done"
