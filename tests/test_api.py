from datetime import UTC, datetime, timedelta

from tests.conftest import WRITER

from agent_taskboard.models import TaskRegisterRequest
from agent_taskboard.store import Store

REGISTER = {
    "title": "Example notes for Alice",
    "task": "Prepare a short example note. Do not include private material.",
    "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
    "group_id": "group_example",
}


def test_register_repeat_keeps_later_status(client, auth, settings):
    created = client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    assert created.status_code == 201
    assert created.json()["status"] == "planned"
    assert created.json()["ui_state"] == "not_started"
    assert created.json()["last_reported_at"].endswith("Z") or "+" in created.json()["last_reported_at"]
    patched = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_example_1", "attempt_id": "attempt_example_1", "status": "accepted"},
    )
    assert patched.status_code == 200
    repeated = client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "accepted"
    assert repeated.json()["revision"] == 2
    changed = dict(REGISTER, title="A different example")
    conflict = client.put("/tasks/job_example_alpha", json=changed, headers=auth)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"
    assert conflict.json()["task"]["title"] == "Example notes for Alice"
    assert WRITER not in conflict.text
    assert not settings.db_path.endswith("missing")


def test_report_key_precedes_revision_and_late_attempt_conflicts(client, auth):
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    first = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_example_1", "attempt_id": "attempt_example_1", "status": "in_progress", "badges": ["waiting_review"]},
    )
    assert first.status_code == 200
    assert first.json()["ui_state"] == "in_progress"
    same = {
        "expected_revision": 1,
        "report_key": "report_example_1",
        "attempt_id": "attempt_example_1",
        "status": "in_progress",
        "badges": ["waiting_review"],
    }
    replay = client.patch("/tasks/job_example_alpha", headers=auth, json=same)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    different = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 2, "report_key": "report_example_1", "attempt_id": "attempt_example_1", "status": "accepted"},
    )
    assert different.status_code == 409
    assert different.json()["code"] == "idempotency_conflict"
    assert different.json()["task"]["task_id"] == "job_example_alpha"
    assert client.get("/tasks/job_example_alpha").json()["revision"] == 2
    handoff = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 2, "report_key": "report_example_2", "attempt_id": "attempt_example_2", "status": "in_progress"},
    )
    assert handoff.status_code == 200
    assert handoff.json()["attempt_id"] == "attempt_example_2"
    late = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 3, "report_key": "report_example_3", "attempt_id": "attempt_example_1", "status": "accepted"},
    )
    assert late.status_code == 409
    assert late.json()["code"] == "stale_attempt"
    assert late.json()["task"]["status"] == "in_progress"
    assert client.get("/tasks/job_example_alpha").json()["status"] == "in_progress"


def test_counts_badges_and_chinese_search(client, auth):
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    client.put(
        "/tasks/job_example_beta",
        headers=auth,
        json={
            "title": "示例笔记",
            "task": "整理一份示例说明。不要写入私人材料。",
            "expected_deliverable": "一份可打开的示例。",
            "group_id": "group_example",
        },
    )
    client.patch(
        "/tasks/job_example_beta",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_beta_1", "status": "cancelled"},
    )
    listed = client.get("/tasks")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    assert body["counts"]["not_started"] == 1
    assert body["counts"]["done"] == 0
    found = client.get("/tasks", params={"q": "示例"})
    assert found.json()["count"] == 0
    included = client.get("/tasks", params={"include_cancelled": True, "q": "示例"})
    assert included.json()["count"] == 1
    assert included.json()["counts"] == {"not_started": 0, "in_progress": 0, "done": 0}
    assert included.json()["tasks"][0]["title"] == "示例笔记"


def test_report_key_is_scoped_to_the_task(client, auth):
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    client.put(
        "/tasks/job_example_beta",
        headers=auth,
        json=dict(REGISTER, title="Example notes for Bob"),
    )
    client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_shared_1", "attempt_id": "attempt_example_1", "status": "in_progress"},
    )
    beta = client.patch(
        "/tasks/job_example_beta",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_shared_1", "attempt_id": "attempt_example_2", "status": "in_progress"},
    )
    assert beta.status_code == 200
    assert beta.json()["task_id"] == "job_example_beta"
    assert beta.json()["attempt_id"] == "attempt_example_2"


def test_accept_from_openapi_example_clears_badges(client, auth):
    schema = client.get("/openapi.json").json()
    examples = schema["paths"]["/tasks/{task_id}"]["patch"]["requestBody"]["content"]["application/json"]["examples"]
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    for name in ("start", "waiting_review", "accept"):
        response = client.patch("/tasks/job_example_alpha", headers=auth, json=examples[name]["value"])
        assert response.status_code == 200, name
    done = client.get("/tasks/job_example_alpha").json()
    assert done["status"] == "accepted"
    assert done["ui_state"] == "done"
    assert done["badges"] == []


def test_extra_key_is_not_reflected(client, auth):
    secret_name = "synthetic-writer-token"
    payload = dict(REGISTER)
    payload[secret_name] = "example"
    response = client.put("/tasks/job_example_alpha", headers=auth, json=payload)
    assert response.status_code == 422
    assert response.json()["fields"] == ["body.unknown_field"]
    assert secret_name not in response.text


def test_read_store_failure_is_json(client, monkeypatch):
    import sqlite3

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(client.app.state.store, "get", boom)
    response = client.get("/tasks/job_example_alpha")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "unavailable"
    assert "database file" not in response.text


def test_null_outcome_keeps_stored_text(client, auth):
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 1, "report_key": "report_example_1", "outcome": "Example outcome for Alice."},
    )
    kept = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 2, "report_key": "report_example_2", "outcome": None},
    )
    assert kept.status_code == 200
    assert kept.json()["outcome"] == "Example outcome for Alice."


def test_path_and_query_locations_stay_safe(client, auth):
    query = client.get("/tasks", params={"group_id": "not a group"})
    assert query.status_code == 422
    assert query.json()["fields"] == ["query.group_id"]
    path = client.get("/tasks/not-a-valid-id")
    assert path.status_code == 422
    assert path.json()["fields"] == ["path.task_id"]
    assert "not-a-valid-id" not in path.text
    assert "not a group" not in query.text


def test_empty_outcome_clears_and_null_badges_clear_on_accept(client, auth):
    client.put("/tasks/job_example_alpha", json=REGISTER, headers=auth)
    client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={
            "expected_revision": 1,
            "report_key": "report_example_1",
            "attempt_id": "attempt_example_1",
            "status": "in_progress",
            "badges": ["waiting_review"],
            "outcome": "Example outcome for Alice.",
        },
    )
    cleared = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 2, "report_key": "report_example_2", "attempt_id": "attempt_example_1", "outcome": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["outcome"] == ""
    accepted = client.patch(
        "/tasks/job_example_alpha",
        headers=auth,
        json={"expected_revision": 3, "report_key": "report_example_3", "attempt_id": "attempt_example_1", "status": "accepted", "badges": None},
    )
    assert accepted.status_code == 200
    assert accepted.json()["badges"] == []
    assert accepted.json()["ui_state"] == "done"


def test_legacy_receipt_reuse_does_not_apply(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE reports (report_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, status_code INTEGER NOT NULL, body_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO reports VALUES (?, ?, 404, ?)",
        ("report_example_1", "job_example_alpha", '{"code":"not_found","message":"No task is stored under that id.","fields":[]}'),
    )
    conn.commit()
    conn.close()
    store = Store(str(path))
    store.register("job_example_alpha", TaskRegisterRequest.model_validate(REGISTER))
    from agent_taskboard.models import TaskPatchRequest
    from agent_taskboard.store import StoreError

    try:
        store.patch(
            "job_example_alpha",
            TaskPatchRequest(expected_revision=1, report_key="report_example_1", status="accepted"),
        )
    except StoreError as exc:
        assert exc.status_code == 409
        assert exc.code == "legacy_receipt_unverifiable"
    else:
        raise AssertionError("legacy key was applied")
    assert store.get("job_example_alpha").status == "planned"


def test_blank_goal_and_secret_free_errors(client, auth):
    blank = client.put("/tasks/job_example_alpha", headers=auth, json=dict(REGISTER, task="   "))
    assert blank.status_code == 422
    assert "   " not in blank.text
    missing = client.put("/tasks/job_example_alpha", json=REGISTER)
    assert missing.status_code == 401
    assert WRITER not in missing.text
    bad_link = client.patch(
        "/tasks/job_missing_01",
        headers=auth,
        json={
            "expected_revision": 1,
            "report_key": "report_example_9",
            "result_refs": [{"kind": "http", "value": "javascript:alert(1)", "label": "bad"}],
        },
    )
    assert bad_link.status_code == 422
    assert "javascript:alert(1)" not in bad_link.text


def test_restart_keeps_accepted(settings):
    from fastapi.testclient import TestClient

    from agent_taskboard.app import create_app

    first = TestClient(create_app(settings))
    first.put("/tasks/job_example_alpha", json=REGISTER, headers={"Authorization": f"Bearer {WRITER}"})
    first.patch(
        "/tasks/job_example_alpha",
        headers={"Authorization": f"Bearer {WRITER}"},
        json={"expected_revision": 1, "report_key": "report_example_1", "status": "accepted"},
    )
    second = TestClient(create_app(settings))
    row = second.get("/tasks/job_example_alpha").json()
    assert row["status"] == "accepted"
    assert row["ui_state"] == "done"


def test_stale_badge_does_not_regress_accepted(tmp_path):
    start = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)
    clock = {"now": start}
    store = Store(str(tmp_path / "board.sqlite3"), stale_after_seconds=60, clock=lambda: clock["now"])
    store.register("job_example_alpha", TaskRegisterRequest.model_validate(REGISTER))
    clock["now"] = start + timedelta(seconds=120)
    stale = store.get("job_example_alpha")
    assert stale.not_updated is True
    assert "stale" in [item.value for item in stale.badges]
    assert stale.ui_state == "not_started"
    from agent_taskboard.models import TaskPatchRequest

    store.patch("job_example_alpha", TaskPatchRequest(expected_revision=1, report_key="report_example_1", status="accepted"))
    clock["now"] = start + timedelta(hours=5)
    done = store.get("job_example_alpha")
    assert done.ui_state == "done"
    assert done.not_updated is False
    assert done.badges == []


def test_event_failure_rolls_back(tmp_path):
    store = Store(str(tmp_path / "board.sqlite3"))
    store.register("job_example_alpha", TaskRegisterRequest.model_validate(REGISTER))

    def boom(*_args, **_kwargs):
        raise RuntimeError("event failed")

    store._insert_event = boom
    from agent_taskboard.models import TaskPatchRequest

    try:
        store.patch("job_example_alpha", TaskPatchRequest(expected_revision=1, report_key="report_example_1", status="in_progress"))
    except RuntimeError:
        pass
    assert store.get("job_example_alpha").revision == 1
