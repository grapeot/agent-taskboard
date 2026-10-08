# RFC: agent-taskboard Architecture and Protocols

## Status
Accepted

## 1. Context and Goals
`agent-taskboard` provides visibility into asynchronous AI agent activities without introducing execution coupling. Agents push status updates over HTTP. Human viewers consume a static one-page dashboard. The system deliberately excludes control mechanisms: there are no task queues, scheduling loops, worker subprocess managers, or approval buttons.

The primary goals are:
- Provide a lightweight HTTP daemon started simply as `python -m agent_taskboard`.
- Store tasks and execution reports reliably in SQLite with optimistic concurrency control.
- Ensure idempotency for network retries and agent restarts.
- Serve a fast, responsive, zero-token web dashboard that displays screen states and diagnostic badges.

## 2. System Architecture

```
+-----------------------------------------------------------+
|                        Client Layer                       |
|                                                           |
|   +-----------------------+     +---------------------+   |
|   |  AI Agent (Producer)  |     |   Browser (Viewer)  |   |
|   |  HTTP Write Requests  |     |   HTML5 + SSE Read  |   |
|   +-----------+-----------+     +----------+----------+   |
+---------------|----------------------------|--------------+
                | Bearer Token               | Unauthenticated
                v                            v
+-----------------------------------------------------------+
|                    HTTP Service Layer                     |
|                                                           |
|   - FastAPI / Starlette routing                           |
|   - Authentication Middleware (Bearer check on writes)    |
|   - CORS Middleware (explicit http/https origins only)    |
|   - SSE Hub (broadcasts change hints on write)            |
|   - Static File Server (serves one-page dashboard)        |
+-----------------------------+-----------------------------+
                              |
                              v
+-----------------------------------------------------------+
|                       Storage Layer                       |
|                                                           |
|   - SQLite (default: ./data/agent_taskboard.sqlite3)      |
|   - Tables: tasks, attempts, reports                      |
|   - WAL mode enabled for concurrent read/write            |
+-----------------------------------------------------------+
```

### 2.1 Process Execution
The service runs directly with Python:
```bash
python -m agent_taskboard
```
A process launcher or supervisor can start this command using the checkout directory as its working directory. There is no CLI for task creation or mutation.

### 2.2 Configuration and Secret Loading
Configuration resolution follows these rules:
1. Environment variables set in the host process take precedence.
2. If `AGENT_TASKBOARD_ENV_FILE` is defined, the service reads that file; otherwise, it reads `.env` in the working directory.
3. The service parses the environment file directly and populates only variables not already present in the environment.
4. Token Validation: The service inspects `AGENT_TASKBOARD_TOKEN`. If the token is empty, missing, or equals `replace-with-a-long-random-token`, the process exits immediately with an error log.
5. Tokens are never placed on command-line arguments and are never delivered to the web browser.

### 2.3 Network Interfaces and CORS
- Default host and port: `127.0.0.1` and `8765`.
- Setting `AGENT_TASKBOARD_HOST=0.0.0.0` and optionally `AGENT_TASKBOARD_PORT=8789` allows access over a trusted local area network or Tailscale interface. This is a local hosting choice, not a public deployment.
- `AGENT_TASKBOARD_CORS_ORIGINS` defaults to an empty list. When set, it must contain a comma-separated list of explicit `http` or `https` origins (e.g., `http://localhost:3000,https://example.com`). Wildcard `*` is explicitly disallowed and rejected during startup.

## 3. Storage and Data Model

The SQLite database file defaults to `./data/agent_taskboard.sqlite3`.

### 3.1 Relational Schema

```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    task TEXT NOT NULL,
    expected_deliverable TEXT NOT NULL,
    group_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_id TEXT,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_reported_at TEXT NOT NULL,
    result_refs_json TEXT NOT NULL,
    owner_session_ref TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    task_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    active INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id, attempt_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    task_id TEXT NOT NULL,
    report_key TEXT NOT NULL,
    receipt_payload TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id, report_key),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_group ON tasks(group_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

The statements above are a sketch of the tables. Request and response fields are defined by `/openapi.json`, not by this sketch.
```

### 3.2 State Derivation Rules

The database stores statuses `planned`, `in_progress`, `accepted`, and `cancelled`. The API computes screen states and badges. `planned` is Not started. `accepted` is Done.

1. **Screen States**:
   - stored `planned` maps to Not started
   - stored `in_progress` maps to In progress
   - stored `accepted` maps to Done. Done is the screen state, not a stored status.

2. **Diagnostic Badges**:
   - `Waiting for review`: Reported when work is submitted for review but not yet stored as `accepted`.
   - `Failed`: Reported when an attempt explicitly records a failure.
   - `Blocked`: Reported when work is held on an external blocker.
   - `Not updated`: Evaluated when stored status is not `accepted` and the report is older than `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default: 1800s).
   - `Unknown`: Fallback when status reporting is inconsistent.

3. **Invariants**:
   - A badge is not `Done`.
   - `Idle` is not a status.
   - A quiet process is not acceptance and is not failure.
   - Accepted rows never receive the `Not updated` badge regardless of how long ago they finished.
   - Cancelled tasks are excluded from `not_started`, `in_progress`, and `done` summary tallies.

## 4. Concurrency and Idempotency Protocols

### 4.1 Report Idempotency via `report_key`
Every progress patch requires a client-generated `report_key` (such as `report_example_1`).
- When a `PATCH` arrives, the server checks the `reports` table for `(task_id, report_key)`.
- If a match exists and the payload hash is the same, the server returns that receipt with its original status, including 404 and 409, before revision and attempt checks.
- A different payload for the same task and key returns 409 `idempotency_conflict` and does not change the row. Send a new report_key.
- A migrated receipt with an empty payload hash cannot be replayed. Reuse returns 409 `legacy_receipt_unverifiable`. The old receipt and the task row stay. Send a new report_key.

### 4.2 Optimistic Locking via `expected_revision`
- Each row carries an integer `revision`, starting at 1 upon registration.
- A `PATCH` request must provide `expected_revision`.
- If `expected_revision != tasks.revision`, the server returns `409 Conflict` containing the current row representation. The caller must fetch or inspect the current state before retrying with an updated revision.

### 4.3 Active Attempt Lifecycle
- Attempt identifiers look like `attempt_example_1`.
- When an attempt is active, incoming `PATCH` requests must supply matching `attempt_id`.
- If an agent transitions work to a new attempt (e.g., following a worker handoff or retry), supplying a new `attempt_id` alongside the current `expected_revision` sets it as the new active attempt.
- Submitting an update for an attempt that is no longer active returns `409 Conflict` with error code `stale_attempt`.

## 5. HTTP Interface Specification

### 5.1 Endpoints Summary

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `PUT` | `/tasks/{task_id}` | Bearer | Register task row |
| `PATCH` | `/tasks/{task_id}` | Bearer | Update task status or attempt |
| `GET` | `/tasks/{task_id}` | None | Retrieve single task record |
| `GET` | `/tasks` | None | List tasks and counts |
| `GET` | `/events` | None | Server-sent event change hints |
| `GET` | `/openapi.json` | None | OpenAPI JSON schema |
| `GET` | `/docs` | None | Interactive Swagger documentation |
| `GET` | `/` | None | Static web dashboard |

### 5.2 Registration: `PUT /tasks/{task_id}`

Example: `PUT /tasks/job_example_alpha`

```json
{
  "title": "Example notes for Alice",
  "task": "Prepare a short example note. Do not include private material.",
  "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
  "group_id": "group_example"
}
```

Response Behaviors:
- **New Task**: Returns `201 Created` with the newly formed task row.
- **Idempotent Resubmission**: If the request body exactly matches the registration fields of the existing row, returns `200 OK` with the current row (including any later attempt or status edits). It does not reset status.
- **Conflict**: If the request body differs from the existing row, returns `409 Conflict` with error code `conflict`. The existing row remains untouched.

### 5.3 Progress Update: `PATCH /tasks/{task_id}`

Example: `PATCH /tasks/job_example_alpha`

```json
{
  "expected_revision": 1,
  "report_key": "report_example_1",
  "attempt_id": "attempt_example_1",
  "status": "in_progress",
  "badges": ["waiting_review"],
  "result_refs": [{"kind": "copy_path", "value": "notes/example.md", "label": "Example note"}],
  "owner_session_ref": "opencode://session/ses_example"
}
```

Response Behaviors:
- Increments `revision` by 1.
- Records `report_key` and receipt payload in `reports`.
- Returns `200 OK` with the updated task row.
- If `expected_revision` does not match, returns `409 Conflict`.
- If `attempt_id` is stale, returns `409 Conflict` (`code: "stale_attempt"`).

### 5.4 List Tasks: `GET /tasks`

Query Parameters:
- `group_id`: String filter.
- `status`: Stored status filter (`planned`, `in_progress`, `accepted`, `cancelled`).
- `ui_state`: Screen-state filter (`not_started`, `in_progress`, `done`, `excluded`).
- `q`: Search substring across title, task, expected deliverable, and group.
- `include_cancelled`: Boolean (default `false`). When `false`, cancelled rows are omitted from the task array.

Response Payload:
```json
{
  "count": 1,
  "counts": {"not_started": 0, "in_progress": 1, "done": 0},
  "tasks": [
    {
      "task_id": "job_example_alpha",
      "title": "Example notes for Alice",
      "task": "Prepare a short example note. Do not include private material.",
      "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
      "group_id": "group_example",
      "status": "in_progress",
      "ui_state": "in_progress",
      "badges": ["waiting_review"],
      "not_updated": false,
      "attempt_id": "attempt_example_1",
      "revision": 2,
      "created_at": "2026-10-07T22:00:00Z",
      "updated_at": "2026-10-07T22:05:00Z",
      "last_reported_at": "2026-10-07T22:05:00Z",
      "result_refs": [{"kind": "copy_path", "value": "notes/example.md", "label": "Example note"}],
      "evidence_refs": [],
      "owner_session_ref": "opencode://session/ses_example",
      "recent_events": []
    }
  ],
  "server_time": "2026-10-07T22:05:00Z"
}
```

Counts sit under `counts`. Cancelled rows are outside those three numbers. They are omitted from `tasks` unless `include_cancelled` is true, in which case `count` includes them and the three counts still do not.

### 5.5 Change Notification: `GET /events`
- Implemented via Server-Sent Events (`text/event-stream`).
- Whenever a `PUT` or `PATCH` mutates state, the server broadcasts a lightweight notification:
  ```
  event: change
  data: {"task_id": "job_example_alpha", "revision": 2, "event_id": "evt_example_1"}
  ```
- The event is a change hint, not an event log. The browser uses this hint to trigger a fresh `GET /tasks`. If hints are missed during disconnections, the dashboard re-fetches upon reconnect.

### 5.6 Error Handling and Response Envelopes
All error responses adhere to the standard envelope:
```json
{
  "code": "validation_error",
    "message": "The request body does not match the typed body.",
    "fields": ["title"]
}
```

Standard codes:
- `401 unauthorized`: Missing or invalid Bearer token.
- `404 not_found`: Task row does not exist.
- `409 conflict` or `stale_attempt`: Concurrency violation or stale attempt. Returns current row state.
- `422 validation_error`: Payload failed validation. Does not echo invalid submitted values back in the response.

## 6. Web Dashboard Architecture

### 6.1 Layout and Rendering
- The dashboard is delivered as a single self-contained HTML document.
- Layout sections:
  1. Header with service title, total counts, and offline status indicator.
  2. Search and filter toolbar.
  3. Pinned Group section at the top.
  4. Open Tasks section displaying all non-accepted rows.
  5. Collapsible `Done` section displaying accepted rows.
- Deliverable Links vs Paths:
  - Valid URLs (`http://`, `https://`, `opencode://`) are rendered as clickable anchors.
  - Local filesystem paths (e.g., `notes/example.md`) are rendered with a copy button to place text onto the clipboard.
- Text Encoding: UTF-8 encoding is strictly enforced so that Chinese titles, goals, and summaries render intact.
- Responsive design rules ensure readable card presentation on narrow mobile viewports.

### 6.2 Offline Resilience
- The browser tracks connection state using window online/offline events and EventSource status.
- When disconnected, an offline badge appears in the header.
- The dashboard preserves the last retrieved data snapshot and avoids marking tasks failed.
- Once connectivity is restored, the client fetches `GET /tasks` to synchronize state.

### 6.3 Security Boundary
- The dashboard contains no secret tokens and makes no authenticated calls.
- The service does not download files, and no artifact route is provided. Deliverable paths are informational references only.
