# Product Requirement Document (PRD)

## Product Name
agent-taskboard

## 1. Problem Statement and Vision
When autonomous AI agents execute multi-step research, coding, or data tasks, human users need a reliable way to observe progress without interrupting execution. Existing workflow engines often impose heavy task execution trees, interactive approval gates, or complex CLI tooling that agents struggle to maintain across restarts and context compactions.

`agent-taskboard` solves this by decoupling execution from visibility. An AI writes task rows over HTTP. A person reads a one-page board in a web browser. The service acts as a stable billboard: it stores delivery goals, tracks active attempts, derives human-friendly screen states, and presents a responsive dashboard. The page has no run, stop, retry, or approve buttons. The service does not schedule or stop agents. There is no task CLI.

## 2. User Personas and Roles

### AI Agent Producer
- Autonomous coding or research assistant running in an execution environment.
- Registers a task before starting long-running or distributed operations.
- Sends incremental progress patches as phases advance or child workers return.
- Updates deliverables and marks completion once work has been verified.

### Human Operator
- Reads the one-page dashboard to understand active goals and deliverable status.
- Inspects progress without managing task queues, retries, or execution buttons.
- Copies local deliverable paths to review outputs on the local workstation, or opens external result links.

## 3. Data Model

### 3.1 Task Rows
- One row represents one delivery goal.
- Task identifiers follow the pattern `job_example_alpha`.
- The task identifier remains constant across retries, context compactions, and subagent handoffs.
- Fields:
  - `task_id`: String identifier (e.g., `job_example_alpha`).
  - `title`: Short descriptive title (supports Chinese and English text).
  - `task`: Narrative description of the delivery goal.
  - `expected_deliverable`: Explicit statement of the required artifact (e.g., `A markdown note whose example link is https://example.com/results/alpha.`).
  - `group_id`: Classification tag (e.g., `group_example`) used for sorting and filtering.
  - `status`: Stored state (`planned`, `in_progress`, `accepted`, `cancelled`). `planned` is Not started. `accepted` is Done.
  - `ui_state`: Screen state (`not_started`, `in_progress`, `done`, `excluded`).
  - `badges`: Diagnostic badges. None of them means Done.
  - `attempt_id`: Current attempt, folded under the row.
  - `revision`: Integer version counter incremented on each update.
  - `last_reported_at`: Server time of the most recent report.
  - `result_refs`: Result links or paths to copy, such as `notes/example.md`.
  - `owner_session_ref`: Session link, such as `opencode://session/ses_example`. It is not a task id.

### 3.2 Attempts
- An attempt represents a concrete execution cycle, such as `attempt_example_1`.
- Attempts are folded under the corresponding task row.
- There is no parent-child task tree.
- Subagent handoffs or retries increment the attempt under the same row without creating nested tasks.

### 3.3 Groups and Links
- `group_example` is a label for sorting and grouping on the board, not a hierarchy.
- Session links are reference pointers to agent logs or transcripts; session links are not task ids.

## 4. Status, Screen States, and Badges

### 4.1 Screen States
The board translates task status into three top-level screen states:
- `Not started`: Registered goal awaiting initial execution.
- `In progress`: Active work underway by the executing agent.
- `Done`: Work completed and accepted (`Done` strictly means accepted).

### 4.2 Diagnostic Badges
Tasks may display one of five diagnostic badges alongside or within open states:
- `Waiting for review`: Deliverable has been produced and awaits verification.
- `Failed`: An attempt encountered an unrecoverable failure.
- `Blocked`: Execution is waiting on an external dependency.
- `Not updated`: An active task has not reported within `AGENT_TASKBOARD_STALE_AFTER_SECONDS`.
- `Unknown`: Unrecognized or unparseable worker state.

### 4.3 Semantics and Invariants
- A badge is not `Done`.
- `Idle` is not a status.
- A quiet process is not acceptance and is not failure.
- Cancelled rows are excluded from the three dashboard counts (`not_started`, `in_progress`, `done`).
- When a task is not accepted and receives no updates within the stale window (`AGENT_TASKBOARD_STALE_AFTER_SECONDS`, default 1800 seconds), it displays the `Not updated` badge.
- Accepted rows do not gain the `Not updated` badge because a report is old.

## 5. Web Dashboard Experience

### 5.1 Page Organization
- Single-page interface without navigation transitions.
- Pinned Group: The operator can pin one group at the top of the board for high-priority tracking.
- Open Rows: Displays all other open tasks across groups on the same page.
- Folded Done Section: Completed and accepted tasks are tucked into a collapsible `Done` section at the bottom.
- Card Information: Each task card displays title, goal, expected deliverable, screen state, last reported timestamp, current attempt, and any result or session links.

### 5.2 Filters and Controls
- Search input matching task title, goal, deliverable, and group.
- A screen-state filter for Not started, In progress, and Done.
- Pin group selector, which sorts that group above other open rows.
- The current page has text search, a three-state filter, and a pin that sorts one group above other open rows. Stored-status, group, and badge filters are later.
- There are no buttons to run, stop, retry, or approve tasks.

### 5.3 Path and Text Display
- Local paths (e.g., `notes/example.md`) are rendered as copyable text blocks, not clickable links. Clicking copies the relative path to the clipboard.
- Remote links (e.g., `https://example.com/results/alpha` or `opencode://session/ses_example`) are presented as clickable external links.
- Chinese characters in task titles, goals, and summaries must remain intact across storage, transmission, and rendering.
- Layout adapts to narrow smartphone and tablet screens as cleanly as desktop monitors.

### 5.4 Connectivity and Live Updates
- The dashboard receives change hints from the server via `GET /events` (Server-Sent Events).
- On initial load, after network reconnection, or upon receiving a change hint, the browser fetches `GET /tasks`.
- A missed hint does not alter stored data.
- If the browser loses network connection, the dashboard displays an offline warning indicator, maintains the last loaded snapshot, and avoids marking tasks failed.
- The web page never contains or requests the authentication token.

## 6. HTTP API Requirements

### 6.1 Authentication
- Write endpoints (`PUT`, `PATCH`) require `Authorization: Bearer <token>`.
- Read endpoints (`GET /tasks`, `GET /tasks/{id}`, `GET /events`, `/openapi.json`, `/docs`) require no authentication.
- The service loads the token from `AGENT_TASKBOARD_TOKEN` or from a `.env` file in the working directory. It never overrides variables already set in the environment.
- The service refuses to start if `AGENT_TASKBOARD_TOKEN` is missing or set to `replace-with-a-long-random-token`.
- The token must never be passed via command line flags or rendered in web assets.

### 6.2 Task Registration (`PUT /tasks/{task_id}`)
- Method: `PUT /tasks/job_example_alpha`
- Body:
  ```json
  {
    "title": "Example notes for Alice",
    "task": "Prepare a short example note. Do not include private material.",
    "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
    "group_id": "group_example"
  }
  ```
- Behavior:
  - First invocation creates the row and returns `201 Created`.
  - Re-submitting the exact same body returns `200 OK` with the current row (including later progress edits) without resetting task status or revision.
  - Submitting a different body for an existing id returns `409 Conflict` and leaves the stored row untouched.

### 6.3 Task Progress (`PATCH /tasks/{task_id}`)
- Method: `PATCH /tasks/job_example_alpha`
- Requires `expected_revision` and `report_key`.
- Idempotency: Submitting a known `report_key` returns the previously stored receipt before checking revisions.
- Attempt Management:
  - Submitting a new attempt identifier with the current revision promotes it to the active attempt.
  - Submitting a patch with an attempt identifier that is no longer active returns `409 Conflict`.
  - If an attempt is active, incoming patches must name it.

### 6.4 Task Reading (`GET /tasks` and `GET /tasks/{task_id}`)
- `GET /tasks/{task_id}`: Returns the single task record or `404 not_found`.
- `GET /tasks`: Returns a list of tasks and a summary counts object:
  ```json excerpt
  {
    "count": 1,
    "counts": {"not_started": 1, "in_progress": 0, "done": 0}
  }
  ```

  The block above is not an executable sample. A complete list body is in `docs/rfc.md`.
- Cancelled rows are excluded from the summary counts (`not_started`, `in_progress`, `done`). They are omitted from `tasks` unless `include_cancelled=true` is requested.
- Supported query parameters: `group_id`, `status`, `ui_state`, `q`, `include_cancelled`.

### 6.5 Change Hints (`GET /events`)
- Server-sent events endpoint emitting lightweight JSON hints when rows change.
- Does not stream an event log or full audit trail; acts solely as a wake-up signal for the client.

### 6.6 Errors and Documentation
- Structured error response format:
  ```json
  {
    "code": "validation_error",
    "message": "The request body does not match the typed body.",
    "fields": ["title"]
  }
  ```
- Error codes: `401 unauthorized`, `404 not_found`, `409 conflict` or `stale_attempt`, `422 validation_error`.
- `422 validation_error` must explain the validation constraint without echoing submitted values.
- Interactive OpenAPI documentation available at `/docs` and schema at `/openapi.json`.

## 7. Operational and Deployment Constraints

### 7.1 Networking and Host Configuration
- Default listen address: `127.0.0.1` port `8765`.
- Operator configuration for trusted local network or Tailscale: set `AGENT_TASKBOARD_HOST=0.0.0.0` and optionally `AGENT_TASKBOARD_PORT=8789`. This is a local hosting choice, not a public web deployment.
- CORS origins: empty by default unless explicitly configured with comma-separated `http` or `https` origins. Wildcard `*` is not supported.

### 7.2 Storage and File Boundaries
- Database default path: `./data/agent_taskboard.sqlite3`.
- The service does not download files.
- There is no artifact route. Deliverable references point to external URLs or local relative paths for human review.

### 7.3 Process Management
- Start command: `python -m agent_taskboard` with no arguments.
- A process launcher can start the service with the project checkout as the working directory.
- No CLI commands exist for mutating tasks.
