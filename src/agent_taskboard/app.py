import asyncio
import hmac
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_taskboard import PHASE, __version__
from agent_taskboard.config import Settings, load_settings
from agent_taskboard.messages import (
    BADGE_RULE,
    CONFLICT,
    IDEMPOTENCY_CONFLICT,
    LEGACY_RECEIPT,
    NOT_FOUND,
    REGISTRATION_CONFLICT,
    STALE_ATTEMPT,
    UNAUTHORIZED,
    UNAVAILABLE,
    VALIDATION_ERROR,
)
from agent_taskboard.models import (
    CONTRACT_MODELS,
    PATCH_EXAMPLES,
    ChangeHint,
    ErrorBody,
    HealthResponse,
    TaskListResponse,
    TaskPatchRequest,
    TaskRegisterRequest,
    TaskSnapshot,
    TaskStatus,
    UiState,
)
from agent_taskboard.store import Receipt, Store, StoreError, utc_now

PHASE_HEADER = "X-Agent-Taskboard-Phase"
TASK_ID = r"^job_[a-z0-9_]{1,64}$"
STATIC_DIR = FilePath(__file__).with_name("static")
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
MESSAGES = {
    "unauthorized": UNAUTHORIZED,
    "not_found": NOT_FOUND,
    "conflict": CONFLICT,
    "stale_attempt": STALE_ATTEMPT,
    "idempotency_conflict": IDEMPOTENCY_CONFLICT,
    "legacy_receipt_unverifiable": LEGACY_RECEIPT,
    "validation_error": VALIDATION_ERROR,
    "unavailable": UNAVAILABLE,
}
KNOWN_FIELDS = {
    "title", "task", "expected_deliverable", "group_id", "expected_revision", "report_key",
    "attempt_id", "status", "badges", "outcome", "result_refs", "evidence_refs",
    "owner_session_ref", "source_ref", "correction_reason", "kind", "value", "label",
    "task_id", "q", "ui_state", "include_cancelled",
}
ERROR_EXAMPLE = {
    "unauthorized": {"code": "unauthorized", "message": UNAUTHORIZED, "fields": [], "task": None},
    "not_found": {"code": "not_found", "message": NOT_FOUND, "fields": [], "task": None},
    "conflict": {"code": "conflict", "message": CONFLICT, "fields": [], "task": None},
    "stale_attempt": {"code": "stale_attempt", "message": STALE_ATTEMPT, "fields": [], "task": None},
    "idempotency_conflict": {"code": "idempotency_conflict", "message": IDEMPOTENCY_CONFLICT, "fields": [], "task": None},
    "validation_error": {"code": "validation_error", "message": VALIDATION_ERROR, "fields": ["title"], "task": None},
    "unavailable": {"code": "unavailable", "message": UNAVAILABLE, "fields": [], "task": None},
}


class Broker:
    def __init__(self) -> None:
        self.subscribers: list[asyncio.Queue] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def publish(self, hint: ChangeHint) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        payload = hint.model_dump(mode="json")
        for queue in list(self.subscribers):
            loop.call_soon_threadsafe(queue.put_nowait, payload)


def _safe_fields(errors: list[dict]) -> list[str]:
    found = []
    for item in errors:
        if item.get("type") == "extra_forbidden":
            found.append("body.unknown_field")
            continue
        parts = [str(part) for part in item.get("loc", [])]
        source = "body"
        names = []
        for part in parts:
            if part in {"path", "query"} and not names:
                source = part
                continue
            if part == "body":
                continue
            names.append(part)
        if not names:
            found.append(source)
            continue
        if any(not part.isdigit() and part not in KNOWN_FIELDS for part in names):
            found.append("body.unknown_field")
            continue
        location = ".".join(names)
        found.append(location if source == "body" else f"{source}.{location}")
    return list(dict.fromkeys(found))


def _error(status_code: int, code: str, message: str, fields: list[str] | None = None, task: TaskSnapshot | None = None) -> JSONResponse:
    body = ErrorBody(code=code, message=message, fields=fields or [], task=task)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _snapshot_response(snapshot: TaskSnapshot, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=snapshot.model_dump(mode="json"))


def _hint(snapshot: TaskSnapshot) -> ChangeHint:
    event_id = snapshot.recent_events[0].event_id if snapshot.recent_events else "evt_example_1"
    return ChangeHint(task_id=snapshot.task_id, revision=snapshot.revision, event_id=event_id)


def require_writer(
    request: Request,
    authorization: str | None = Header(
        default=None,
        description="Bearer write token from the server environment. The page does not send this header. The example is a placeholder, not a working credential.",
        examples=["Bearer replace-with-a-long-random-token"],
    ),
) -> None:
    settings: Settings = request.app.state.settings
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    if not settings.token or not hmac.compare_digest(supplied, settings.token):
        raise HTTPException(status_code=401)


def enrich_openapi(schema: dict) -> dict:
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        components.pop(name, None)
    for model in CONTRACT_MODELS:
        body = components.get(model.__name__)
        if body is None:
            raw = model.model_json_schema()
            raw.pop("$defs", None)
            components[model.__name__] = raw
            body = raw
        props = body.setdefault("properties", {})
        for fname, finfo in model.model_fields.items():
            prop = props.setdefault(fname, {})
            if finfo.description:
                prop["description"] = finfo.description
            if finfo.examples:
                prop["examples"] = list(finfo.examples)
    return schema


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = Store(settings.db_path, stale_after_seconds=settings.stale_after_seconds)
    broker = Broker()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.broker.loop = asyncio.get_running_loop()
        yield

    app = FastAPI(
        title="agent-taskboard",
        version=__version__,
        description=(
            "Local read-only task board. An AI writes rows over HTTP. A person reads them in a browser. "
            "Read /openapi.json before sending a body."
        ),
        lifespan=lifespan,
        servers=[
            {
                "url": f"http://{settings.host}:{settings.port}",
                "description": "Bind address from the process environment. The default is loopback, not a public host.",
            }
        ],
    )
    app.state.settings = settings
    app.state.store = store
    app.state.broker = broker

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            servers=app.servers,
        )
        app.openapi_schema = enrich_openapi(schema)
        return app.openapi_schema

    app.openapi = custom_openapi
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "PUT", "PATCH"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def phase_header(request: Request, call_next):
        response = await call_next(request)
        response.headers[PHASE_HEADER] = PHASE
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 401:
            return _error(401, "unauthorized", UNAUTHORIZED)
        return _error(exc.status_code, "unavailable", UNAVAILABLE)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = _safe_fields(exc.errors())
        message = VALIDATION_ERROR
        if "badges" in fields or any("badge" in item.get("msg", "").lower() or "waiting_review" in item.get("msg", "") for item in exc.errors()):
            fields = ["badges"]
            message = BADGE_RULE
        return _error(422, "validation_error", message, fields)

    def publish(snapshot: TaskSnapshot) -> None:
        app.state.broker.publish(_hint(snapshot))

    def write_error(exc: StoreError) -> JSONResponse:
        if exc.code == "stale_attempt":
            message = STALE_ATTEMPT
        elif exc.code == "idempotency_conflict":
            message = IDEMPOTENCY_CONFLICT
        elif exc.code == "legacy_receipt_unverifiable":
            message = LEGACY_RECEIPT
        elif exc.message.startswith("Registration"):
            message = REGISTRATION_CONFLICT
        else:
            message = MESSAGES.get(exc.code, exc.message)
        return _error(exc.status_code, exc.code, message, task=exc.task)

    @app.get("/health", response_model=HealthResponse, summary="Health", description="Process is serving HTTP and can store task writes.", operation_id="get_health", tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="agent-taskboard", phase=PHASE)

    @app.get(
        "/",
        response_class=HTMLResponse,
        summary="Read-only board",
        description="One page that reads the snapshot. It does not include the write token and has no run, stop, retry, or approve controls.",
        operation_id="get_board_page",
        tags=["board"],
        responses={200: {"description": "Board HTML."}},
    )
    def board_page() -> HTMLResponse:
        path = STATIC_DIR / "index.html"
        if not path.is_file():
            return HTMLResponse("Board page is missing from the package.", status_code=500)
        return HTMLResponse(path.read_bytes(), headers=PAGE_HEADERS)

    @app.put(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        status_code=201,
        summary="Register a logical task",
        description=(
            "Create a row. The same registration body returns the current row and does not reset status. "
            "A different body for the same id is 409 and leaves the row unchanged."
        ),
        operation_id="register_task",
        tags=["tasks"],
        responses={
            200: {"model": TaskSnapshot, "description": "The registration matches the stored row. The current row is returned."},
            201: {"model": TaskSnapshot, "description": "The row was created with status planned."},
            401: {"model": ErrorBody, "description": "Missing or wrong write token."},
            409: {"model": ErrorBody, "description": "Registration content differs. The current row is included and was not changed."},
            422: {"model": ErrorBody, "description": "The body or path does not match the typed contract. Unknown keys are body.unknown_field. Submitted values are not echoed."},
            500: {"model": ErrorBody, "description": "The store failed. The response is JSON and does not include a path or token."},
        },
    )
    def register_task(
        body: TaskRegisterRequest,
        task_id: str = Path(description="Stable logical task id. Retries keep this id. It is not a session id.", examples=["job_example_alpha"], pattern=TASK_ID),
        _writer: None = Depends(require_writer),
    ) -> JSONResponse:
        try:
            status_code, snapshot = app.state.store.register(task_id, body)
        except StoreError as exc:
            return write_error(exc)
        except sqlite3.Error:
            return _error(500, "unavailable", UNAVAILABLE)
        if status_code == 201:
            publish(snapshot)
        return _snapshot_response(snapshot, status_code)

    @app.patch(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        summary="Update a logical task",
        description=(
            "Apply a report. report_key is scoped to this task id. The same payload replays the first receipt, including 404 and 409, before revision checks. "
            "A different payload for the same task and key is 409 idempotency_conflict. "
            "expected_revision must then match. A new attempt id becomes active. "
            "An attempt id that is no longer active is 409 and does not change the row. "
            "accepted means the caller checked the deliverable. Omitting badges when setting accepted or cancelled clears them."
        ),
        operation_id="update_task",
        tags=["tasks"],
        responses={
            200: {"model": TaskSnapshot, "description": "The report was stored, or the same payload is replaying the first 200 receipt for this task and report_key."},
            401: {"model": ErrorBody, "description": "Missing or wrong write token."},
            404: {"model": ErrorBody, "description": "No row is stored under that id."},
            409: {
                "model": ErrorBody,
                "description": "conflict, stale_attempt, or idempotency_conflict. A stored 409 receipt is replayed when the same payload is retried. A different payload for the same task and report_key is idempotency_conflict and does not apply. The current row of this task is included when it exists. Another task's row is never returned.",
            },
            422: {"model": ErrorBody, "description": "The body or path does not match the typed contract. Unknown keys are reported as body.unknown_field. Submitted values are not echoed."},
            500: {"model": ErrorBody, "description": "The store failed. Retry. The response is JSON and does not include a path or token."},
        },
    )
    def update_task(
        body: Annotated[TaskPatchRequest, Body(openapi_examples=PATCH_EXAMPLES)],
        task_id: str = Path(description="Stable logical task id. Retries keep this id. It is not a session id.", examples=["job_example_alpha"], pattern=TASK_ID),
        _writer: None = Depends(require_writer),
    ) -> JSONResponse:
        try:
            snapshot = app.state.store.patch(task_id, body)
        except Receipt as receipt:
            return JSONResponse(status_code=receipt.status_code, content=receipt.body)
        except StoreError as exc:
            return write_error(exc)
        except ValueError as exc:
            text = str(exc)
            if "badge" in text or "waiting_review" in text:
                return _error(422, "validation_error", BADGE_RULE, ["badges"])
            if "attempt_id" in text:
                return _error(422, "validation_error", "attempt_id is required while an attempt is active.", ["attempt_id"])
            return _error(422, "validation_error", VALIDATION_ERROR, ["body"])
        except sqlite3.Error:
            return _error(500, "unavailable", UNAVAILABLE)
        publish(snapshot)
        return _snapshot_response(snapshot, 200)

    @app.get(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        summary="Read one task",
        description="Return the current row. The write token is not required.",
        operation_id="get_task",
        tags=["tasks"],
        responses={
            200: {"model": TaskSnapshot, "description": "The current row."},
            404: {"model": ErrorBody, "description": "No row is stored under that id."},
            422: {"model": ErrorBody, "description": "The task id does not match the typed pattern."},
            500: {"model": ErrorBody, "description": "The store failed. The response is JSON and does not include a path or token."},
        },
    )
    def get_task(
        task_id: str = Path(description="Stable logical task id.", examples=["job_example_alpha"], pattern=TASK_ID),
    ) -> JSONResponse:
        try:
            return _snapshot_response(app.state.store.get(task_id), 200)
        except StoreError as exc:
            return write_error(exc)
        except sqlite3.Error:
            return _error(500, "unavailable", UNAVAILABLE)

    @app.get(
        "/tasks",
        response_model=TaskListResponse,
        summary="Read the current snapshot",
        description="Return matching rows, the row count, and the three screen-state counts. Cancelled rows are omitted unless include_cancelled is true, and they stay outside those three counts.",
        operation_id="list_tasks",
        tags=["tasks"],
        responses={
            200: {"description": "Current rows and counts."},
            422: {"model": ErrorBody, "description": "A filter does not match the typed contract. Unknown keys are body.unknown_field."},
            500: {"model": ErrorBody, "description": "The store failed. The response is JSON and does not include a path or token."},
        },
    )
    def list_tasks(
        group_id: str | None = Query(default=None, description="Limit to one group id.", examples=["group_example"], pattern=r"^group_[a-z0-9_]{1,64}$"),
        status: TaskStatus | None = Query(default=None, description="Limit to one stored status.", examples=["in_progress"]),
        ui_state: UiState | None = Query(default=None, description="Limit to one screen state.", examples=["in_progress"]),
        q: str | None = Query(default=None, description="Case-insensitive match on id, title, goal, deliverable, or group.", examples=["Alice"], max_length=200),
        include_cancelled: bool = Query(default=False, description="Include cancelled rows. They are still excluded from the three counts.", examples=[False]),
    ) -> TaskListResponse:
        try:
            tasks, counts = app.state.store.list_tasks(
                group_id=group_id,
                status=status.value if status else None,
                ui_state=ui_state.value if ui_state else None,
                query=q,
                include_cancelled=include_cancelled,
            )
        except sqlite3.Error:
            return _error(500, "unavailable", UNAVAILABLE)
        return TaskListResponse(tasks=tasks, count=len(tasks), counts=counts, server_time=utc_now())

    @app.get(
        "/events",
        summary="Change hint stream",
        description="Server-sent change hints. Read GET /tasks on open, on reconnect, and after a hint. This stream is not a replay log and is not the stored state.",
        operation_id="task_events",
        tags=["events"],
        responses={
            200: {
                "description": "text/event-stream of ChangeHint events named change. A ready comment is sent on connect.",
                "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/ChangeHint"}}},
            }
        },
    )
    async def task_events() -> StreamingResponse:
        queue = app.state.broker.subscribe()

        async def generate() -> AsyncIterator[str]:
            try:
                yield ": ready\n\n"
                while True:
                    try:
                        hint = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: change\ndata: {json.dumps(hint, ensure_ascii=False)}\n\n"
            finally:
                app.state.broker.unsubscribe(queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
