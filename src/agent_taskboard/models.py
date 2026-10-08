from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class UiState(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"
    excluded = "excluded"


class LinkKind(StrEnum):
    http = "http"
    opencode = "opencode"
    copy_path = "copy_path"


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
        description="Goal and boundary. Not a full prompt.",
        examples=["Prepare a short example note. Do not include private material."],
        min_length=1,
        max_length=2000,
    )
    expected_deliverable: str = Field(
        description="Observable result, including where it will be or how to tell it is done.",
        examples=["A markdown note whose example link is https://example.com/results/alpha."],
        min_length=1,
        max_length=2000,
    )
    group_id: str = Field(
        description="Batch or theme id. Pattern group_ plus lowercase letters, digits, and underscores.",
        examples=["group_example"],
        pattern=r"^group_[a-z0-9_]{1,64}$",
    )


class TaskPatchRequest(APIModel):
    expected_revision: int = Field(
        description="Revision from the last read. A mismatch is a conflict in the later phase.",
        examples=[1],
        ge=1,
    )
    report_key: str = Field(
        description="Stable key for this report. The same key returns the same receipt before revision is checked.",
        examples=["report_example_1"],
        pattern=r"^[A-Za-z0-9_-]{8,200}$",
    )
    attempt_id: str | None = Field(
        default=None,
        description="Active attempt, when one exists. A late attempt must not close a newer attempt.",
        examples=["attempt_example_1"],
        pattern=r"^attempt_[a-z0-9_]{1,64}$",
    )
    title: str | None = Field(
        default=None,
        description="Replacement title.",
        examples=["Example notes for Alice"],
        min_length=1,
        max_length=200,
    )
    task: str | None = Field(
        default=None,
        description="Replacement goal and boundary.",
        examples=["Prepare a short example note. Do not include private material."],
        min_length=1,
        max_length=2000,
    )
    expected_deliverable: str | None = Field(
        default=None,
        description="Replacement observable result.",
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
            "Replacement status. planned is Not started, in_progress is In progress, "
            "accepted is Done, cancelled leaves the three-state count."
        ),
        examples=["in_progress"],
    )
    badges: list[Badge] | None = Field(
        default=None,
        description="Badges on the last known state. They do not mean Done. idle is not a badge.",
        examples=[["waiting_review"]],
    )
    outcome: str | None = Field(
        default=None,
        description="Short result note from the reporter. Not proof of acceptance.",
        examples=["Example outcome for Alice."],
        max_length=2000,
    )
    result_refs: list[ResultLink] | None = Field(
        default=None,
        description="Result links or paths to copy. At most 20.",
        examples=[[{"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"}]],
        max_length=20,
    )
    evidence_refs: list[ResultLink] | None = Field(
        default=None,
        description="Evidence links. Same link rules as result_refs.",
        examples=[[{"kind": "opencode", "value": "opencode://session/ses_example", "label": "Example session"}]],
        max_length=20,
    )
    owner_session_ref: str | None = Field(
        default=None,
        description="Session link for the current owner. Not a task id.",
        examples=["opencode://session/ses_example"],
        max_length=2000,
    )
    source_ref: str | None = Field(
        default=None,
        description="Optional source label, such as a handoff note. Not a secret.",
        examples=["example-handoff"],
        max_length=200,
    )
    correction_reason: str | None = Field(
        default=None,
        description="Why a later correction was made.",
        examples=["Example correction, not a live edit."],
        max_length=2000,
    )

    @model_validator(mode="after")
    def check_combo(self) -> Self:
        if self.status is not None and self.badges is not None:
            validate_status_badges(self.status, self.badges)
        if self.owner_session_ref is not None:
            ResultLink(kind=LinkKind.opencode, value=self.owner_session_ref, label="session")
        return self


class TaskSnapshot(APIModel):
    task_id: str = Field(
        description="Stable logical task id. Retries keep this id. It is not a session id.",
        examples=["job_example_alpha"],
        pattern=r"^job_[a-z0-9_]{1,64}$",
    )
    title: str = Field(
        description="Short title for scanning the board.",
        examples=["Example notes for Alice"],
    )
    task: str = Field(
        description="Goal and boundary. Not a full prompt.",
        examples=["Prepare a short example note. Do not include private material."],
    )
    expected_deliverable: str = Field(
        description="Observable result the row is aiming at.",
        examples=["A markdown note whose example link is https://example.com/results/alpha."],
    )
    group_id: str = Field(
        description="Batch or theme id.",
        examples=["group_example"],
    )
    status: TaskStatus = Field(
        description="Stored status. planned, in_progress, accepted, or cancelled.",
        examples=["in_progress"],
    )
    ui_state: UiState = Field(
        description=(
            "Screen state. not_started is Not started, in_progress is In progress, "
            "done is Done and means accepted, excluded is cancelled and is outside the three-state count. "
            "Badges do not change this value. idle is not a state."
        ),
        examples=["in_progress"],
    )
    badges: list[Badge] = Field(
        description="waiting_review, failed, blocked, or stale. None of these means Done.",
        examples=[["waiting_review"]],
    )
    revision: int = Field(
        description="Server revision. Clients send it back as expected_revision.",
        examples=[1],
        ge=1,
    )
    updated_at: str = Field(
        description="UTC time the row was last stored, ISO-8601.",
        examples=[EXAMPLE_TIME],
    )
    last_reported_at: str = Field(
        description="UTC time of the last AI report, ISO-8601. A gap means not updated, not done or failed.",
        examples=[EXAMPLE_TIME],
    )
    attempt_id: str | None = Field(
        default=None,
        description="Current attempt, folded under the task id.",
        examples=["attempt_example_1"],
    )
    owner_session_ref: str | None = Field(
        default=None,
        description="Session link for the current owner.",
        examples=["opencode://session/ses_example"],
    )
    source_ref: str | None = Field(
        default=None,
        description="Optional source label.",
        examples=["example-handoff"],
    )
    result_refs: list[ResultLink] = Field(
        description="Result links or paths to copy.",
        examples=[[{"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"}]],
    )
    evidence_refs: list[ResultLink] = Field(
        description="Evidence links.",
        examples=[[{"kind": "opencode", "value": "opencode://session/ses_example", "label": "Example session"}]],
    )
    outcome: str | None = Field(
        default=None,
        description="Latest outcome note. Not proof of acceptance.",
        examples=["Example outcome for Alice."],
    )


class TaskListResponse(APIModel):
    tasks: list[TaskSnapshot] = Field(
        description="Current rows. This scaffold build does not return this body.",
        examples=[[]],
    )
    server_time: str = Field(
        description="UTC time of this read, ISO-8601. Use it with last_reported_at. It is not a process heartbeat.",
        examples=[EXAMPLE_TIME],
    )


class ChangeHint(APIModel):
    task_id: str = Field(
        description="Task whose row changed. The client reads the snapshot again. This is not a replay log.",
        examples=["job_example_alpha"],
    )
    revision: int = Field(
        description="Revision to read.",
        examples=[2],
        ge=1,
    )
    event_id: str = Field(
        description="Id of this hint.",
        examples=["evt_example_1"],
        pattern=r"^evt_[a-z0-9_]{1,64}$",
    )


class ErrorBody(APIModel):
    code: str = Field(
        description="Stable machine-readable error code.",
        examples=["not_implemented"],
    )
    message: str = Field(
        description="What the caller should do next. This does not confirm a saved task.",
        examples=["Task routes are published as scaffold stubs and do not store tasks in this build."],
    )
    fields: list[str] = Field(
        default_factory=list,
        description="Field locations for a validation error. Values are not echoed.",
        examples=[["body.title"]],
    )


class HealthResponse(APIModel):
    status: str = Field(
        description="ok means the process is serving HTTP.",
        examples=["ok"],
    )
    phase: str = Field(
        description="scaffold means task storage is not implemented.",
        examples=["scaffold"],
    )
    service: str = Field(
        description="Service name.",
        examples=["agent-taskboard"],
    )


CONTRACT_MODELS = (
    ResultLink,
    TaskRegisterRequest,
    TaskPatchRequest,
    TaskSnapshot,
    TaskListResponse,
    ChangeHint,
    ErrorBody,
    HealthResponse,
)
