# Product Requirements Document

## Overview

agent-taskboard is a small local HTTP service and task board. An AI writes task rows over HTTP. A person reads them in a browser. The intended public repository is https://github.com/grapeot/agent-taskboard. License: MIT. Default branch: master.

This repository checkout is a scaffold. The package can be imported as `agent_taskboard`. In this scaffold phase, `GET /health` is live and its JSON includes phase scaffold, `GET /` serves a static placeholder page, and the typed task endpoints are documented in OpenAPI but return HTTP 501 Not Implemented. The scaffold does not store tasks.

## Target Users

1. **Human operators**: A person reading the board on the same machine, or later on a trusted LAN or Tailscale, without buttons that run or stop work.
2. **AI coding agents**: Producers such as Codex, Claude Code, Cursor, or OpenCode that report goals, attempts, and result links through typed HTTP requests.

## Requirements

### Current Scaffold Requirements

- Provide an importable Python package `agent_taskboard`.
- Implement `GET /health` returning status 200 and JSON that includes `"phase": "scaffold"`.
- Implement `GET /` returning a static, read-only HTML placeholder page with no scripts, no forms, and no external assets.
- Publish OpenAPI schema and documentation at `http://127.0.0.1:8765/openapi.json` and `http://127.0.0.1:8765/docs` when the service is started on the default bind.
- `PUT` and `PATCH` require a bearer token. A valid token returns 501. A missing or wrong token returns 401. `GET /tasks`, `GET /events`, and `GET /artifacts/{artifact_id}` return 501 and do not use the write token, so the page never has to carry it.
- No database file must be created on disk during tests or scaffold execution.

### Future Implementation Requirements

- **Service Architecture**: The service will run as a resident FastAPI application backed by Pydantic 2 models and a local SQLite file (`./data/agent_taskboard.sqlite3`). It is not an in-memory store and not a CLI with subcommands. The execution command is `python -m agent_taskboard` with no arguments.
- **Task Identity and Rows**: One row represents one delivery goal. Retries, handoffs, or multiple attempts keep the same task identifier (for example, `job_example_alpha`) and fold attempts underneath (such as `attempt_example_1`). Session identifiers are distinct from task identifiers.
- **Three Screen States Only**:
  - `Not started`
  - `In progress`
  - `Done` (Done means accepted)
  - Badges on the last known state: `Waiting for review`, `Failed`, `Blocked`, and `Stale`. These are status badges attached to the last known screen state; they do not form a fourth screen state, and they are not `Done`.
  - Idle is not a status. A quiet process does not imply acceptance or failure.
- **Reporting Recency**: Display the last reported timestamp. A long gap in reported time indicates that the task has not been updated; it does not indicate completion or failure.
- **Read-Only Interface**: The web page must remain read-only. It must contain no run, stop, retry, or approve buttons. The service does not schedule, spawn, or kill processes.
- **Authentication**: Write requests require an `Authorization: Bearer <token>` header matching `AGENT_TASKBOARD_TOKEN`. The HTML page must never contain the token. Notifications sent in future phases must never contain the token.
- **Network Defaults**: The service defaults to binding at `127.0.0.1` on port `8765`. An operator may explicitly set the bind host to `0.0.0.0` for a trusted LAN or Tailscale. Exposing the read-only dashboard on a trusted LAN is a conscious choice, not a public internet default.
- **Links and Artifacts**: Allowed URL schemes for result links are `http`, `https`, and `opencode://` (for example `https://example.com/results/alpha` and `opencode://session/ses_example`). Schemes such as `javascript`, `data`, and `file` are rejected. Local references must be inline text or opaque artifact identifiers resolved against configured directories (`notes/example.md`). No open directory browsing is supported.
- **Configuration**: Configuration relies on six environment variables:
  - `AGENT_TASKBOARD_HOST` (default `127.0.0.1`)
  - `AGENT_TASKBOARD_PORT` (default `8765`)
  - `AGENT_TASKBOARD_DB_PATH` (default `./data/agent_taskboard.sqlite3`)
  - `AGENT_TASKBOARD_TOKEN` (default `replace-with-a-long-random-token`)
  - `AGENT_TASKBOARD_CORS_ORIGINS` (default empty, meaning no extra browser origins)
  - `AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS` (default empty)

## Success Criteria

1. Verification passes offline with `python -m ruff check .` and `python -m pytest`.
2. OpenAPI documents all planned typed schemas clearly at `/openapi.json`.
3. Clear architectural boundaries ensure that this scaffold does not purport to store data or manage live processes.

## Non-Goals

- Scheduling, restarting, or terminating agents or tasks.
- In-memory temporary task lists or interactive CLI task management.
- Fourth screen states or treating status badges as independent screen states.
- Treating silent tasks as failed or finished.
- Exposing an open filesystem browser or supporting raw `file://` URIs.
- Default exposure to the public internet or permissive CORS headers (`Access-Control-Allow-Origin: *`).
- Sending emails or managing user accounts.
