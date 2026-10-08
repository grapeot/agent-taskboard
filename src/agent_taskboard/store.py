import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_taskboard.models import (
    Badge,
    BoardCounts,
    ResultLink,
    TaskEvent,
    TaskPatchRequest,
    TaskRegisterRequest,
    TaskSnapshot,
    TaskStatus,
    project_ui_state,
    validate_status_badges,
)

PUBLIC_PLACEHOLDER = "replace-with-a-long-random-token"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stored timestamp is missing a timezone")
    return parsed.astimezone(UTC)


def patch_hash(body: TaskPatchRequest) -> str:
    raw = body.model_dump(mode="json", exclude_none=True)
    text = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def fingerprint(body: TaskRegisterRequest) -> str:
    payload = {
        "title": body.title,
        "task": body.task,
        "expected_deliverable": body.expected_deliverable,
        "group_id": body.group_id,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class StoreError(Exception):
    def __init__(self, status_code: int, code: str, message: str, task: TaskSnapshot | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.task = task


class Receipt(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body


class Store:
    def __init__(self, path: str, stale_after_seconds: int = 1800, clock=utc_now):
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.clock = clock
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    task TEXT NOT NULL,
                    expected_deliverable TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    badges_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_reported_at TEXT NOT NULL,
                    attempt_id TEXT,
                    owner_session_ref TEXT,
                    source_ref TEXT,
                    result_refs_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    outcome TEXT,
                    correction_reason TEXT,
                    registration_fingerprint TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, attempt_id)
                )
                """
            )
            self._migrate_reports(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    report_key TEXT,
                    attempt_id TEXT,
                    status TEXT NOT NULL,
                    correction_reason TEXT
                )
                """
            )

    def _migrate_reports(self, conn) -> None:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reports'").fetchone()
        if row is None:
            conn.execute(
                """
                CREATE TABLE reports (
                    task_id TEXT NOT NULL,
                    report_key TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY (task_id, report_key)
                )
                """
            )
            return
        info = list(conn.execute("PRAGMA table_info(reports)"))
        names = [item[1] for item in info]
        primary = [item[1] for item in info if item[5]]
        if primary == ["task_id", "report_key"] and "payload_hash" in names:
            return
        conn.execute(
            """
            CREATE TABLE reports_scoped (
                task_id TEXT NOT NULL,
                report_key TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                body_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                PRIMARY KEY (task_id, report_key)
            )
            """
        )
        if "payload_hash" in names:
            conn.execute(
                "INSERT INTO reports_scoped (task_id, report_key, status_code, body_json, payload_hash) "
                "SELECT task_id, report_key, status_code, body_json, payload_hash FROM reports"
            )
        else:
            conn.execute(
                "INSERT INTO reports_scoped (task_id, report_key, status_code, body_json, payload_hash) "
                "SELECT task_id, report_key, status_code, body_json, '' FROM reports"
            )
        conn.execute("DROP TABLE reports")
        conn.execute("ALTER TABLE reports_scoped RENAME TO reports")

    def register(self, task_id: str, body: TaskRegisterRequest) -> tuple[int, TaskSnapshot]:
        digest = fingerprint(body)
        now = self.clock()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                if row is not None:
                    current = self._snapshot(conn, row, now)
                    if row["registration_fingerprint"] != digest:
                        conn.execute("ROLLBACK")
                        raise StoreError(
                            409,
                            "conflict",
                            "Registration content differs from the stored task. The current row was left unchanged.",
                            current,
                        )
                    conn.execute("COMMIT")
                    return 200, current
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, title, task, expected_deliverable, group_id, status, badges_json,
                        revision, created_at, updated_at, last_reported_at, attempt_id,
                        owner_session_ref, source_ref, result_refs_json, evidence_refs_json,
                        outcome, correction_reason, registration_fingerprint
                    ) VALUES (?, ?, ?, ?, ?, 'planned', '[]', 1, ?, ?, ?, NULL, NULL, NULL, '[]', '[]', NULL, NULL, ?)
                    """,
                    (task_id, body.title, body.task, body.expected_deliverable, body.group_id, _iso(now), _iso(now), _iso(now), digest),
                )
                self._insert_event(conn, task_id, 1, now, None, None, TaskStatus.planned, None)
                conn.execute("COMMIT")
            except StoreError:
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return 201, self.get(task_id)

    def patch(self, task_id: str, body: TaskPatchRequest) -> TaskSnapshot:
        now = self.clock()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                digest = patch_hash(body)
                prior = conn.execute(
                    "SELECT status_code, body_json, payload_hash FROM reports WHERE task_id = ? AND report_key = ?",
                    (task_id, body.report_key),
                ).fetchone()
                if prior is not None:
                    if prior["payload_hash"] == "":
                        current_row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                        current = self._snapshot(conn, current_row, now) if current_row is not None else None
                        conn.execute("COMMIT")
                        raise StoreError(
                            409,
                            "legacy_receipt_unverifiable",
                            "This report_key was stored before payload checks. Send a new report_key. The stored row was not changed.",
                            current,
                        )
                    if prior["payload_hash"] == digest:
                        conn.execute("COMMIT")
                        raise Receipt(prior["status_code"], json.loads(prior["body_json"]))
                    current_row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                    current = self._snapshot(conn, current_row, now) if current_row is not None else None
                    conn.execute("COMMIT")
                    raise StoreError(
                        409,
                        "idempotency_conflict",
                        "This report_key was already used for a different payload on this task. Send a new report_key. The stored row was not changed.",
                        current,
                    )
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                if row is None:
                    receipt = {"code": "not_found", "message": "No task is stored under that id.", "fields": []}
                    self._save_receipt(conn, body.report_key, task_id, 404, receipt, digest)
                    conn.execute("COMMIT")
                    raise Receipt(404, receipt)
                current = self._snapshot(conn, row, now)
                if body.expected_revision != row["revision"]:
                    self._conflict(conn, body.report_key, task_id, "conflict", current, digest)
                self._check_attempt(conn, task_id, row["attempt_id"], body.attempt_id, body.report_key, current, digest)
                updated = self._apply(conn, row, body, now)
                conn.execute("COMMIT")
                return updated
            except (StoreError, Receipt):
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _conflict(self, conn, report_key: str, task_id: str, code: str, current: TaskSnapshot, digest: str) -> None:
        message = (
            "That attempt is no longer active. A late report cannot change the current attempt."
            if code == "stale_attempt"
            else "The revision or attempt does not match the stored task. Read the current task and send a new report key."
        )
        receipt = {
            "code": code,
            "message": message,
            "fields": [],
            "task": current.model_dump(mode="json"),
        }
        self._save_receipt(conn, report_key, task_id, 409, receipt, digest)
        conn.execute("COMMIT")
        raise StoreError(409, code, message, current)

    def _check_attempt(self, conn, task_id: str, active: str | None, incoming: str | None, report_key: str, current: TaskSnapshot, digest: str) -> None:
        if active and not incoming:
            raise ValueError("attempt_id is required while an attempt is active")
        if incoming is None or incoming == active:
            return
        previous = conn.execute(
            "SELECT active FROM attempts WHERE task_id = ? AND attempt_id = ?",
            (task_id, incoming),
        ).fetchone()
        if previous is not None and not previous["active"]:
            self._conflict(conn, report_key, task_id, "stale_attempt", current, digest)

    def _apply(self, conn, row: sqlite3.Row, body: TaskPatchRequest, now: datetime) -> TaskSnapshot:
        status = TaskStatus(body.status) if body.status is not None else TaskStatus(row["status"])
        explicit_badges = "badges" in body.model_fields_set and body.badges is not None
        if body.status in {TaskStatus.accepted, TaskStatus.cancelled} and not explicit_badges:
            badges = []
        elif explicit_badges:
            badges = list(body.badges)
        else:
            badges = [Badge(item) for item in json.loads(row["badges_json"])]
        validate_status_badges(status, badges)
        attempt_id = body.attempt_id if body.attempt_id is not None else row["attempt_id"]
        if body.attempt_id and body.attempt_id != row["attempt_id"]:
            conn.execute("UPDATE attempts SET active = 0 WHERE task_id = ?", (row["task_id"],))
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM attempts WHERE task_id = ?",
                (row["task_id"],),
            ).fetchone()["n"]
            conn.execute(
                """
                INSERT INTO attempts (task_id, attempt_id, sequence, active, started_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (row["task_id"], body.attempt_id, sequence, _iso(now)),
            )
        revision = row["revision"] + 1
        values = {
            "title": body.title if body.title is not None else row["title"],
            "task": body.task if body.task is not None else row["task"],
            "expected_deliverable": body.expected_deliverable if body.expected_deliverable is not None else row["expected_deliverable"],
            "group_id": body.group_id if body.group_id is not None else row["group_id"],
            "status": status.value,
            "badges_json": json.dumps([item.value for item in badges], ensure_ascii=False),
            "revision": revision,
            "updated_at": _iso(now),
            "last_reported_at": _iso(now),
            "attempt_id": attempt_id,
            "owner_session_ref": body.owner_session_ref if body.owner_session_ref is not None else row["owner_session_ref"],
            "source_ref": body.source_ref if body.source_ref is not None else row["source_ref"],
            "result_refs_json": json.dumps([item.model_dump() for item in body.result_refs], ensure_ascii=False)
            if body.result_refs is not None
            else row["result_refs_json"],
            "evidence_refs_json": json.dumps([item.model_dump() for item in body.evidence_refs], ensure_ascii=False)
            if body.evidence_refs is not None
            else row["evidence_refs_json"],
            "outcome": body.outcome if body.outcome is not None else row["outcome"],
            "correction_reason": body.correction_reason if body.correction_reason is not None else row["correction_reason"],
        }
        assignments = ", ".join(f"{key} = ?" for key in values)
        conn.execute(
            f"UPDATE tasks SET {assignments} WHERE task_id = ?",
            (*values.values(), row["task_id"]),
        )
        self._insert_event(conn, row["task_id"], revision, now, body.report_key, attempt_id, status, values["correction_reason"])
        updated = self._snapshot(conn, conn.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone(), now)
        self._save_receipt(conn, body.report_key, row["task_id"], 200, updated.model_dump(mode="json"), patch_hash(body))
        return updated

    def _insert_event(self, conn, task_id, revision, now, report_key, attempt_id, status, correction_reason) -> None:
        conn.execute(
            """
            INSERT INTO events (event_id, task_id, revision, created_at, report_key, attempt_id, status, correction_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"evt_{uuid.uuid4().hex}", task_id, revision, _iso(now), report_key, attempt_id, status.value, correction_reason),
        )

    def _save_receipt(self, conn, report_key: str, task_id: str, status_code: int, body: dict, digest: str) -> None:
        conn.execute(
            "INSERT INTO reports (task_id, report_key, status_code, body_json, payload_hash) VALUES (?, ?, ?, ?, ?)",
            (task_id, report_key, status_code, json.dumps(body, ensure_ascii=False), digest),
        )

    def get(self, task_id: str) -> TaskSnapshot:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise StoreError(404, "not_found", "No task is stored under that id.")
            return self._snapshot(conn, row, self.clock())

    def list_tasks(self, *, group_id: str | None, status: str | None, ui_state: str | None, query: str | None, include_cancelled: bool) -> tuple[list[TaskSnapshot], BoardCounts]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC, task_id ASC").fetchall()
            now = self.clock()
            tasks = [self._snapshot(conn, row, now) for row in rows]
        needle = (query or "").casefold()
        selected = []
        for task in tasks:
            if group_id and task.group_id != group_id:
                continue
            if status and task.status != status:
                continue
            if ui_state and task.ui_state != ui_state:
                continue
            if needle and needle not in " ".join((task.task_id, task.title, task.task, task.expected_deliverable, task.group_id)).casefold():
                continue
            if not include_cancelled and task.status == TaskStatus.cancelled:
                continue
            selected.append(task)
        counts = BoardCounts(
            not_started=sum(task.ui_state == "not_started" for task in selected),
            in_progress=sum(task.ui_state == "in_progress" for task in selected),
            done=sum(task.ui_state == "done" for task in selected),
        )
        return selected, counts

    def _snapshot(self, conn, row: sqlite3.Row, now: datetime) -> TaskSnapshot:
        status = TaskStatus(row["status"])
        stored = [Badge(item) for item in json.loads(row["badges_json"])]
        last_reported = _parse(row["last_reported_at"])
        badges = list(stored)
        not_updated = False
        if status not in {TaskStatus.accepted, TaskStatus.cancelled} and self.stale_after_seconds > 0:
            if now - last_reported > timedelta(seconds=self.stale_after_seconds):
                not_updated = True
                if Badge.stale not in badges:
                    badges.append(Badge.stale)
        events = [
            TaskEvent(
                event_id=item["event_id"],
                revision=item["revision"],
                created_at=_parse(item["created_at"]),
                report_key=item["report_key"],
                attempt_id=item["attempt_id"],
                status=TaskStatus(item["status"]),
                correction_reason=item["correction_reason"],
            )
            for item in conn.execute(
                """
                SELECT * FROM events WHERE task_id = ? ORDER BY revision DESC LIMIT 5
                """,
                (row["task_id"],),
            )
        ]
        return TaskSnapshot(
            task_id=row["task_id"],
            title=row["title"],
            task=row["task"],
            expected_deliverable=row["expected_deliverable"],
            group_id=row["group_id"],
            status=status,
            ui_state=project_ui_state(status, stored),
            badges=badges,
            not_updated=not_updated,
            revision=row["revision"],
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            last_reported_at=last_reported,
            attempt_id=row["attempt_id"],
            owner_session_ref=row["owner_session_ref"],
            source_ref=row["source_ref"],
            result_refs=[ResultLink.model_validate(item) for item in json.loads(row["result_refs_json"])],
            evidence_refs=[ResultLink.model_validate(item) for item in json.loads(row["evidence_refs_json"])],
            outcome=row["outcome"],
            correction_reason=row["correction_reason"],
            recent_events=events,
        )
