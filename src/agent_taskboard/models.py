from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXAMPLE_TIME = "2026-10-07T21:00:00Z"


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskStatus(StrEnum):
    planned = "planned"
    in_progress = "in_progress"
    accepted = "accepted"
    cancelled = "cancelled"


class Badge(StrEnum):
    waiting_review = "waiting_review"
    failed = "failed"
    blocked = "blocked"
    stale = "stale"
    unknown = "unknown"


class UiState(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"
    excluded = "excluded"


class ErrorCode(StrEnum):
    unauthorized = "unauthorized"
    not_found = "not_found"
    conflict = "conflict"
    stale_attempt = "stale_attempt"
    idempotency_conflict = "idempotency_conflict"
    legacy_receipt_unverifiable = "legacy_receipt_unverifiable"
    validation_error = "validation_error"
    unavailable = "unavailable"


class LinkKind(StrEnum):
    http = "http"
    opencode = "opencode"
    copy_path = "copy_path"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _strip_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def validate_status_badges(status: TaskStatus, badges: list[Badge]) -> None:
    found = set(badges)
    if status == TaskStatus.cancelled and found:
        raise ValueError("cancelled has no badges")
    if status == TaskStatus.accepted and found:
        raise ValueError("accepted does not carry badges and does not decay")
    if Badge.waiting_review in found and status != TaskStatus.in_progress:
        raise ValueError("waiting_review only applies while in progress")


def project_ui_state(status: TaskStatus, badges: list[Badge] | None = None) -> UiState:
    found = list(badges or [])
    validate_status_badges(status, found)
    if status == TaskStatus.cancelled:
        return UiState.excluded
    if status == TaskStatus.accepted:
        return UiState.done
    if status == TaskStatus.planned:
        return UiState.not_started
    return UiState.in_progress


class ResultLink(APIModel):
    kind: LinkKind = Field(
        description=(
            "http is an http(s) URL. opencode is an opencode:// link. "
            "copy_path is text to copy, not a navigation target."
        ),
        examples=["http"],
    )
    value: str = Field(
        description="Link target or path text. javascript, data, and file URLs are rejected.",
        examples=["https://example.com/results/alpha"],
        min_length=1,
        max_length=2000,
    )
    label: str = Field(
        description="Short label shown next to the link.",
        examples=["Example result"],
        min_length=1,
        max_length=200,
    )

    @model_validator(mode="after")
    def check_value(self) -> Self:
        value = self.value
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("value must not have surrounding space or control characters")
        lowered = value.lower()
        if lowered.startswith(("javascript:", "data:", "file:", "vbscript:")):
            raise ValueError("scheme is not allowed")
        if self.kind == LinkKind.http:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("http links must be http or https URLs with a host")
            if parsed.username or parsed.password:
                raise ValueError("credentials in URLs are not allowed")
        elif self.kind == LinkKind.opencode:
            parsed = urlsplit(value)
            if parsed.scheme != "opencode" or not (parsed.netloc or parsed.path.strip("/")):
                raise ValueError("opencode links must use the opencode scheme and a path")
        elif "://" in value or ".." in value.split("/"):
            raise ValueError("copy_path is plain text and must not contain ..")
        return self


class TaskRegisterRequest(APIModel):
    title: str = Field(
        description="Short title for scanning the board.",
        examples=["Example notes for Alice"],
        min_length=1,
        max_length=200,
    )
    task: str = Field(
        description="Goal and boundary. Not a full prompt. Required, and not blank.",
        examples=["Prepare a short example note. Do not include private material."],
        min_length=1,
        max_length=2000,
    )
    expected_deliverable: str = Field(
        description="Observable result, including where it will be or how to tell it is done. Required, and not blank.",
        examples=["A markdown note whose example link is https://example.com/results/alpha."],
        min_length=1,
        max_length=2000,
    )
    group_id: str = Field(
        description="Batch or theme id used for sorting. Not a parent task. Pattern group_ plus lowercase letters, digits, and underscores.",
        examples=["group_example"],
        pattern=r"^group_[a-z0-9_]{1,64}$",
    )

    @field_validator("title", "task", "expected_deliverable")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = _strip_text(value)
        if stripped is None:
            raise ValueError("must not be blank")
        return stripped


class TaskPatchRequest(APIModel):
    expected_revision: int = Field(
        description="Revision from the last read. Checked after report_key. A mismatch is a conflict.",
        examples=[1],
        ge=1,
    )
    report_key: str = Field(
        description=(
            "Idempotency key scoped to this task id, not to the whole service. "
            "The same payload on this task returns the first receipt with its original status, including 404 or 409, before revision checks. "
            "A different payload for this task and key is 409 idempotency_conflict and does not change the row. "
            "A receipt migrated without a payload hash cannot be replayed: reuse returns 409 legacy_receipt_unverifiable. Send a new report_key. "
            "The same key on another task is a separate report."
        ),
        examples=["report_example_1"],
        pattern=r"^[A-Za-z0-9_-]{8,200}$",
    )
    attempt_id: str | None = Field(
        default=None,
        description=(
            "Attempt folded under the task id. A new id with the current revision becomes active. "
            "An id that is no longer active is a conflict. Required while an attempt is active."
        ),
        examples=["attempt_example_1"],
        pattern=r"^attempt_[a-z0-9_]{1,64}$",
    )
    title: str | None = Field(default=None, description="Replacement title.", examples=["Example notes for Alice"], min_length=1, max_length=200)
    task: str | None = Field(
        default=None,
        description="Replacement goal and boundary. Not blank when sent.",
        examples=["Prepare a short example note. Do not include private material."],
        min_length=1,
        max_length=2000,
    )
    expected_deliverable: str | None = Field(
        default=None,
        description="Replacement observable result. Not blank when sent.",
        examples=["A markdown note whose example link is https://example.com/results/alpha."],
        min_length=1,
        max_length=2000,
    )
    group_id: str | None = Field(
        default=None,
        description="Replacement group id.",
        examples=["group_example"],
        pattern=r"^group_[a-z0-9_]{1,64}$",
    )
    status: TaskStatus | None = Field(
        default=None,
        description=(
            "Stored status. planned is Not started, in_progress is In progress, accepted is Done, cancelled leaves the three counts. "
            "accepted means the caller checked the deliverable. Idle, exit, or a quiet runtime does not set it. "
            "Omitted or null leaves the stored status. Sending accepted or cancelled with badges omitted or null clears stored badges."
        ),
        examples=["in_progress"],
    )
    badges: list[Badge] | None = Field(
        default=None,
        description=(
            "Replacement badge list. waiting_review, failed, blocked, stale, or unknown. None of these means Done. idle is not a badge. "
            "Omitted or null keeps the stored list, except when status is accepted or cancelled: omitted or null badges clear them. "
            "An explicit incompatible list is 422 on badges. Send [] to clear. waiting_review requires in_progress."
        ),
        examples=[["waiting_review"]],
    )
    outcome: str | None = Field(
        default=None,
        description="Short result note. Not proof of acceptance. Omitted or null keeps the stored note. An empty string replaces it with empty text.",
        examples=["Example outcome for Alice."],
        max_length=2000,
    )
    result_refs: list[ResultLink] | None = Field(
        default=None,
        description="Full replacement list of result links or paths to copy. At most 20. Send [] to clear. Omitted or null keeps the stored list.",
        examples=[[{"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"}]],
        max_length=20,
    )
    evidence_refs: list[ResultLink] | None = Field(
        default=None,
        description="Full replacement list of evidence links. Same link rules as result_refs. Send [] to clear. Omitted or null keeps the stored list.",
        examples=[[{"kind": "opencode", "value": "opencode://session/ses_example", "label": "Example session"}]],
        max_length=20,
    )
    owner_session_ref: str | None = Field(
        default=None,
        description="Session link for the current owner. Not a task id, and not rewritten to a project. Omitted or null keeps the stored link.",
        examples=["opencode://session/ses_example"],
        max_length=2000,
    )
    source_ref: str | None = Field(
        default=None,
        description="Optional source label, such as a handoff note. Not a secret. Omitted or null keeps the stored label.",
        examples=["example-handoff"],
        max_length=200,
    )
    correction_reason: str | None = Field(
        default=None,
        description="Why a later correction was made. Stored with the new revision. Omitted or null keeps the stored reason.",
        examples=["Example correction, not a live edit."],
        max_length=2000,
    )

    @field_validator("title", "task", "expected_deliverable")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _strip_text(value)

    @model_validator(mode="after")
    def check_combo(self) -> Self:
        if self.status is not None and self.badges is not None:
            validate_status_badges(self.status, self.badges)
        if self.owner_session_ref is not None:
            ResultLink(kind=LinkKind.opencode, value=self.owner_session_ref, label="session")
        return self


class TaskEvent(APIModel):
    event_id: str = Field(description="Id of this stored change.", examples=["evt_example_1"], pattern=r"^evt_[a-z0-9_]{1,64}$")
    revision: int = Field(description="Task revision written in the same transaction.", examples=[1], ge=1)
    created_at: datetime = Field(description="UTC time the change was stored.", examples=[EXAMPLE_TIME])
    report_key: str | None = Field(default=None, description="Report key for a patch. Empty for the registration event.", examples=["report_example_1"])
    attempt_id: str | None = Field(default=None, description="Attempt id after this change.", examples=["attempt_example_1"])
    status: TaskStatus = Field(description="Status stored with this change.", examples=["planned"])
    correction_reason: str | None = Field(default=None, description="Correction note stored with this change.", examples=["Example correction, not a live edit."])

    @field_validator("created_at")
    @classmethod
    def aware_created(cls, value: datetime) -> datetime:
        return _aware(value)


class TaskSnapshot(APIModel):
    task_id: str = Field(
        description="Stable logical task id. Retries and handoffs keep this id. It is not a session id.",
        examples=["job_example_alpha"],
        pattern=r"^job_[a-z0-9_]{1,64}$",
    )
    title: str = Field(description="Short title for scanning the board.", examples=["Example notes for Alice"])
    task: str = Field(description="Goal and boundary. Not a full prompt.", examples=["Prepare a short example note. Do not include private material."])
    expected_deliverable: str = Field(
        description="Observable result the row is aiming at.",
        examples=["A markdown note whose example link is https://example.com/results/alpha."],
    )
    group_id: str = Field(description="Batch or theme id used for sorting. Not a parent task.", examples=["group_example"])
    status: TaskStatus = Field(description="Stored status. planned, in_progress, accepted, or cancelled.", examples=["in_progress"])
    ui_state: UiState = Field(
        description=(
            "Screen state. not_started is Not started, in_progress is In progress, "
            "done is Done and means accepted, excluded is cancelled and is outside the three counts. "
            "Badges do not change this value. idle is not a state."
        ),
        examples=["in_progress"],
    )
    badges: list[Badge] = Field(
        description=(
            "waiting_review, failed, blocked, stale, or unknown. None of these means Done. "
            "stale may be added at read time when a non-accepted row is older than the stale window. It is not stored."
        ),
        examples=[["waiting_review"]],
    )
    not_updated: bool = Field(
        description="True when a non-accepted row is older than the stale window. Accepted rows stay false. This is not a process status.",
        examples=[False],
    )
    revision: int = Field(description="Server revision. Send it back as expected_revision.", examples=[1], ge=1)
    created_at: datetime = Field(description="UTC time the row was registered.", examples=[EXAMPLE_TIME])
    updated_at: datetime = Field(description="UTC time the row was last stored.", examples=[EXAMPLE_TIME])
    last_reported_at: datetime = Field(
        description="UTC time of the last AI report, set by the server. A gap means not updated, not done or failed.",
        examples=[EXAMPLE_TIME],
    )
    attempt_id: str | None = Field(default=None, description="Current attempt, folded under the task id.", examples=["attempt_example_1"])
    owner_session_ref: str | None = Field(default=None, description="Session link for the current owner. Open it as stored.", examples=["opencode://session/ses_example"])
    source_ref: str | None = Field(default=None, description="Optional source label.", examples=["example-handoff"])
    result_refs: list[ResultLink] = Field(
        description="Result links or paths to copy.",
        examples=[[{"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"}]],
    )
    evidence_refs: list[ResultLink] = Field(
        description="Evidence links.",
        examples=[[{"kind": "opencode", "value": "opencode://session/ses_example", "label": "Example session"}]],
    )
    outcome: str | None = Field(default=None, description="Latest outcome note. Not proof of acceptance.", examples=["Example outcome for Alice."])
    correction_reason: str | None = Field(default=None, description="Latest correction note.", examples=["Example correction, not a live edit."])
    recent_events: list[TaskEvent] = Field(
        description="Up to five newest stored changes. Not a tool-call log and not a parent tree.",
        examples=[[]],
    )

    @field_validator("created_at", "updated_at", "last_reported_at")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        return _aware(value)


class BoardCounts(APIModel):
    not_started: int = Field(description="Rows in this response whose screen state is Not started. Cancelled rows are not included.", examples=[1], ge=0)
    in_progress: int = Field(description="Rows in this response whose screen state is In progress. Badges do not move a row out of this count.", examples=[1], ge=0)
    done: int = Field(description="Rows in this response whose screen state is Done. Done means accepted.", examples=[0], ge=0)


class TaskListResponse(APIModel):
    tasks: list[TaskSnapshot] = Field(description="Rows matching the query. Cancelled rows are omitted unless include_cancelled is true.", examples=[[]])
    count: int = Field(description="Number of rows in tasks. May exceed the three counts when cancelled rows are included.", examples=[1], ge=0)
    counts: BoardCounts = Field(description="Three screen-state counts for the rows in this response.", examples=[{"not_started": 1, "in_progress": 0, "done": 0}])
    server_time: datetime = Field(description="UTC time of this read. Use it with last_reported_at. It is not a process heartbeat.", examples=[EXAMPLE_TIME])

    @field_validator("server_time")
    @classmethod
    def aware_server_time(cls, value: datetime) -> datetime:
        return _aware(value)


class ChangeHint(APIModel):
    task_id: str = Field(description="Task whose row changed. Read GET /tasks again. This hint is not a replay log.", examples=["job_example_alpha"])
    revision: int = Field(description="Revision to read.", examples=[2], ge=1)
    event_id: str = Field(description="Id of the stored change.", examples=["evt_example_1"])


class ErrorBody(APIModel):
    code: ErrorCode = Field(
        description=(
            "unauthorized: send the server bearer token. not_found: the task id is absent; use a new report_key after creating it. "
            "conflict: read task.revision and send a new report_key. stale_attempt: use the current attempt_id and a new report_key. "
            "idempotency_conflict: this task already used the report_key for another payload; send a new report_key. "
            "legacy_receipt_unverifiable: the stored receipt has no payload hash; send a new report_key. The old receipt and row stay. "
            "validation_error: fix the named fields. unavailable: retry the read or write; the row was not silently changed."
        ),
        examples=["conflict"],
    )
    message: str = Field(description="What the caller should do next. Submitted values and the write token are not echoed.", examples=["The revision or attempt does not match the stored task. Read the current task and send a new report key."])
    fields: list[str] = Field(
        default_factory=list,
        description=(
            "Safe locations only. A body field is title or badges. A path error is path.task_id. "
            "A query error is query.group_id or query.status. An unknown extra key is body.unknown_field. Values are not echoed."
        ),
        examples=[["title"]],
    )
    task: TaskSnapshot | None = Field(
        default=None,
        description=(
            "Current row of this task for conflict, stale_attempt, idempotency_conflict, and legacy_receipt_unverifiable when the row exists. "
            "Null when the row does not exist."
        ),
        examples=[None],
    )


class HealthResponse(APIModel):
    status: str = Field(description="ok means the process is serving HTTP.", examples=["ok"])
    service: str = Field(description="Service name.", examples=["agent-taskboard"])
    phase: str = Field(description="ready means task writes are stored.", examples=["ready"])


PATCH_EXAMPLES = {
    "start": {
        "summary": "Start work on the registered row",
        "value": {
            "expected_revision": 1,
            "report_key": "report_example_1",
            "attempt_id": "attempt_example_1",
            "status": "in_progress",
        },
    },
    "waiting_review": {
        "summary": "Report that the attempt is ready for review",
        "value": {
            "expected_revision": 2,
            "report_key": "report_example_2",
            "attempt_id": "attempt_example_1",
            "status": "in_progress",
            "badges": ["waiting_review"],
        },
    },
    "accept": {
        "summary": "Caller accepts the deliverable. Omitting badges clears them.",
        "value": {
            "expected_revision": 3,
            "report_key": "report_example_3",
            "attempt_id": "attempt_example_1",
            "status": "accepted",
        },
    },
    "recover_conflict": {
        "summary": "After 409, use the current revision and a new report key",
        "value": {
            "expected_revision": 3,
            "report_key": "report_example_4",
            "attempt_id": "attempt_example_1",
            "status": "in_progress",
        },
    },
}


CONTRACT_MODELS = (
    ResultLink,
    TaskRegisterRequest,
    TaskPatchRequest,
    TaskEvent,
    TaskSnapshot,
    BoardCounts,
    TaskListResponse,
    ChangeHint,
    ErrorBody,
    HealthResponse,
)
