import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from agent_taskboard.app import create_app

pytestmark = pytest.mark.browser


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(settings):
    port = _port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("server did not start")
    yield base
    server.should_exit = True
    thread.join(timeout=5)


def test_board_renders_synthetic_tasks(live_server, auth, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    out = Path(os.environ.get("AGENT_TASKBOARD_SCREENSHOT_DIR", "test-artifacts/screenshots"))
    out.mkdir(parents=True, exist_ok=True)
    headers = auth
    httpx.put(
        f"{live_server}/tasks/job_example_alpha",
        headers=headers,
        json={
            "title": "Example notes for Alice",
            "task": "Prepare a short example note. Do not include private material.",
            "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
            "group_id": "group_example",
        },
    ).raise_for_status()
    httpx.patch(
        f"{live_server}/tasks/job_example_alpha",
        headers=headers,
        json={
            "expected_revision": 1,
            "report_key": "report_example_1",
            "attempt_id": "attempt_example_1",
            "status": "in_progress",
            "badges": ["waiting_review"],
            "result_refs": [
                {"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"},
                {"kind": "copy_path", "value": "notes/example.md", "label": "Example note"},
            ],
            "owner_session_ref": "opencode://session/ses_example",
        },
    ).raise_for_status()
    httpx.put(
        f"{live_server}/tasks/job_example_beta",
        headers=headers,
        json={
            "title": "示例笔记",
            "task": "整理一份示例说明。不要写入私人材料。",
            "expected_deliverable": "一份可打开的示例。",
            "group_id": "group_example",
        },
    ).raise_for_status()
    dialogs = []
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for name, width, height in (("desktop", 1280, 800), ("mobile", 390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("dialog", lambda dialog: dialogs.append(dialog.message) or dialog.dismiss())
                page.goto(live_server, wait_until="networkidle")
                page.get_by_text("示例笔记").wait_for()
                page.get_by_text("Waiting for review").wait_for()
                page.screenshot(path=str(out / f"{name}.png"), full_page=True)
                page.close()
        finally:
            browser.close()
    assert dialogs == []
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            delayed = {"n": 0}

            def handle(route):
                delayed["n"] += 1
                if delayed["n"] == 1:
                    time.sleep(0.3)
                    route.fulfill(json={"tasks": [], "count": 0, "counts": {"not_started": 0, "in_progress": 0, "done": 0}, "server_time": "2026-10-07T21:00:00Z"})
                else:
                    route.continue_()

            page.route("**/tasks", handle)
            page.goto(live_server, wait_until="networkidle")
            page.get_by_text("示例笔记").wait_for()
            page.wait_for_timeout(500)
            assert page.get_by_text("示例笔记").count() == 1
        finally:
            browser.close()
    assert (out / "desktop.png").stat().st_size > 1000
    assert (out / "mobile.png").stat().st_size > 1000
