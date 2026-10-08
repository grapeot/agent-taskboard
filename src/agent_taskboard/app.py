import hmac
from pathlib import Path as FilePath

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from agent_taskboard import PHASE, __version__
from agent_taskboard.config import Settings, load_settings
from agent_taskboard.messages import NOT_IMPLEMENTED, UNAUTHORIZED, VALIDATION_ERROR
from agent_taskboard.models import (
    CONTRACT_MODELS,
    ChangeHint,
    ErrorBody,
    HealthResponse,
    TaskListResponse,
    TaskPatchRequest,
    TaskRegisterRequest,
    TaskSnapshot,
)

PHASE_HEADER = "X-Agent-Taskboard-Phase"
TASK_ID = r"^job_[a-z0-9_]{1,64}$"
ARTIFACT_ID = r"^art_[a-z0-9_]{1,64}$"
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _error(status_code: int, code: str, message: str, fields: list[str] | None = None) -> JSONResponse:
    body = ErrorBody(code=code, message=message, fields=fields or [])
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _contract_responses(*codes: int) -> dict[int, dict[str, object]]:
    notes = {
        401: "Missing or wrong write token.",
        404: "Implementation contract. This scaffold build returns 501 instead.",
        409: "Implementation contract for a stale revision or a late attempt. This scaffold build returns 501 instead.",
        422: "The body or path does not match the typed contract. Submitted values are not echoed.",
        501: "This scaffold build does not store tasks, stream events, or open files.",
    }
    return {code: {"model": ErrorBody, "description": notes[code]} for code in codes}


def require_writer(
    request: Request,
    authorization: str | None = Header(
        default=None,
        description="Bearer write token from the server environment. The page does not send this header.",
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
        if not body:
            continue
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
    app = FastAPI(
        title="agent-taskboard",
        version=__version__,
        description=(
            "Scaffold build of a local read-only task board. "
            "GET /health and GET / are live. Task routes are typed and return 501 until storage is implemented."
        ),
        servers=[
            {
                "url": f"http://{settings.host}:{settings.port}",
                "description": "Bind address from the process environment. The default is loopback, not a public host.",
            }
        ],
    )
    app.state.settings = settings

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
        if exc.status_code == 501:
            return _error(501, "not_implemented", NOT_IMPLEMENTED)
        return _error(exc.status_code, "error", NOT_IMPLEMENTED)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item.get("loc", []) if part != "body")
            if loc:
                fields.append(loc)
        return _error(422, "validation_error", VALIDATION_ERROR, fields)

    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Health",
        description="Process is serving HTTP. phase is scaffold until task storage exists.",
        operation_id="get_health",
        tags=["health"],
    )
    def health() -> HealthResponse:
        return HealthResponse(status="ok", phase=PHASE, service="agent-taskboard")

    @app.get(
        "/",
        response_class=HTMLResponse,
        summary="Read-only placeholder page",
        description="Static scaffold page. It does not list stored tasks and it does not include the write token.",
        operation_id="get_board_page",
        tags=["board"],
        responses={200: {"description": "Placeholder HTML. Not a live board."}},
    )
    def board_page() -> HTMLResponse:
        path = FilePath(__file__).with_name("static") / "index.html"
        if not path.is_file():
            return HTMLResponse("Placeholder page is missing from the package.", status_code=500)
        return HTMLResponse(path.read_bytes(), headers=PAGE_HEADERS)

    @app.put(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        summary="Register a logical task",
        description=(
            "Later phase: the same body returns the stored row and does not overwrite a later update. "
            "A different body for the same id conflicts. "
            "This scaffold build does not store the row. A valid write token gets 501. "
            "A missing or wrong token gets 401."
        ),
        operation_id="register_task",
        tags=["tasks"],
        responses=_contract_responses(401, 409, 422, 501),
    )
    def register_task(
        task_id: str = Path(
            description="Stable logical task id. Retries keep this id. It is not a session id.",
            examples=["job_example_alpha"],
            pattern=TASK_ID,
        ),
        _body: TaskRegisterRequest = ...,
        _writer: None = Depends(require_writer),
    ) -> TaskSnapshot:
        if not task_id:
            raise HTTPException(status_code=422)
        raise HTTPException(status_code=501)

    @app.patch(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        summary="Update a logical task",
        description=(
            "Later phase: expected_revision must match, and report_key is judged first. "
            "The same report_key returns the same receipt. A late attempt gets 409 and must not close a newer attempt. "
            "This scaffold build does not apply the patch. A valid write token gets 501. "
            "A missing or wrong token gets 401."
        ),
        operation_id="update_task",
        tags=["tasks"],
        responses=_contract_responses(401, 404, 409, 422, 501),
    )
    def update_task(
        task_id: str = Path(
            description="Stable logical task id. Retries keep this id. It is not a session id.",
            examples=["job_example_alpha"],
            pattern=TASK_ID,
        ),
        _body: TaskPatchRequest = ...,
        _writer: None = Depends(require_writer),
    ) -> TaskSnapshot:
        if not task_id:
            raise HTTPException(status_code=422)
        raise HTTPException(status_code=501)

    @app.get(
        "/tasks",
        response_model=TaskListResponse,
        summary="Read the current snapshot",
        description=(
            "Later phase: the current rows. The page refetches this after a change hint. "
            "This scaffold build returns 501 and does not require the write token."
        ),
        operation_id="list_tasks",
        tags=["tasks"],
        responses=_contract_responses(422, 501),
    )
    def list_tasks(
        group_id: str | None = Query(
            default=None,
            description="Optional group filter. Pattern group_ plus lowercase letters, digits, and underscores.",
            examples=["group_example"],
            pattern=r"^group_[a-z0-9_]{1,64}$",
        ),
    ) -> TaskListResponse:
        if group_id is not None and not group_id:
            raise HTTPException(status_code=422)
        raise HTTPException(status_code=501)

    @app.get(
        "/events",
        response_model=ChangeHint,
        summary="Change hint stream",
        description=(
            "Later phase: SSE change hints, not a replay log. The client reads GET /tasks again. "
            "This scaffold build returns 501 and does not stream."
        ),
        operation_id="task_events",
        tags=["events"],
        responses={
            200: {
                "description": "Implementation contract: text/event-stream of ChangeHint. This build does not emit it.",
                "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/ChangeHint"}}},
            },
            **_contract_responses(501),
        },
    )
    def task_events() -> ChangeHint:
        raise HTTPException(status_code=501)

    @app.get(
        "/artifacts/{artifact_id}",
        summary="Read one registered artifact",
        description=(
            "Later phase: bytes for an opaque artifact id under configured roots. "
            "A raw filesystem path is not accepted. "
            "This scaffold build returns 501 and does not open files."
        ),
        operation_id="read_artifact",
        tags=["artifacts"],
        responses={
            200: {
                "description": "Implementation contract: file bytes. This build does not return them.",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            **_contract_responses(404, 422, 501),
        },
    )
    def read_artifact(
        artifact_id: str = Path(
            description="Opaque artifact id. Not a filesystem path.",
            examples=["art_example_alpha"],
            pattern=ARTIFACT_ID,
        ),
    ) -> None:
        if not artifact_id:
            raise HTTPException(status_code=422)
        raise HTTPException(status_code=501)

    return app
