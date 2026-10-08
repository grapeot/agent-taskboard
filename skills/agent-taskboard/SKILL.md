---
name: agent-taskboard
description: Register delivery goals and report progress to agent-taskboard over HTTP.
---

# agent-taskboard Skill

Use this skill to publish tasks and report progress to an `agent-taskboard` service instance. An AI writes task rows over HTTP. A person reads a one-page board. The page has no run, stop, retry, or approve buttons. The service does not schedule or stop agents. There is no task CLI.

## Producer Rules for the Caller

Follow these rules in this exact order because later steps use earlier results:

1. Read the host AGENTS.md or CLAUDE.md and any routing file before editing discovery. If the host has rules/skills/INDEX.md or skills/INDEX.md, add a pointer to skills/agent-taskboard/SKILL.md. Otherwise add a short pointer in AGENTS.md or CLAUDE.md. Install only that one skill.
2. Clone https://github.com/grapeot/agent-taskboard to a persistent checkout. The host pointer must name that checkout's skills/agent-taskboard/SKILL.md, not a path relative to the host repository root.
3. In that checkout run uv venv --python 3.12, activate it, and uv pip install -e '.[dev]'. Copy .env.example to .env and replace the placeholder with a random token generated locally. Do not print the token or commit .env.
4. Start python -m agent_taskboard from that directory. Read /openapi.json before sending a body.
5. Create one job_ id and reuse it. PUT the goal and expected deliverable before dispatch.
6. PATCH when work starts, when something material changes, and when a child returns. report_key belongs to that task id. Retry the same payload with the same key. A different payload needs a new key.
7. On 409, read the current row and send a new report key. Do not reuse the old attempt id after a handoff.
8. The main thread sets status accepted only after it has checked the deliverable. Omitting badges on that patch clears them. Failure, unknown, and partial work stay unfinished. Do not treat a quiet or idle runtime as Done.

## Core Data Model and Semantics

- **One row is one delivery goal**: A task identifier looks like `job_example_alpha` and stays the same across retries and handoffs.
- **Attempts**: An attempt identifier looks like `attempt_example_1` and is folded under that row. There is no parent-child task tree.
- **Grouping**: `group_example` is a label used to pin a group at the top. It is not a hierarchy, and the page does not filter by badge.
- **Session links**: Reference links such as `opencode://session/ses_example` point to agent session transcripts. Session links are not task ids.
- **Screen States**: `Not started`, `In progress`, and `Done`. `Done` strictly means accepted.
- **Diagnostic Badges**: `Waiting for review`, `Failed`, `Blocked`, `Not updated`, and `Unknown`.
- **Invariants**:
  - A badge is not `Done`.
  - `Idle` is not a status.
  - A quiet process is not acceptance and is not failure.
  - Cancelled rows are excluded from the three summary counts (`not_started`, `in_progress`, `done`).
  - An unaccepted row that has not received a report within `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default 1800 seconds) shows `Not updated`. Accepted rows do not gain that badge because a report is old.

## API Contracts and Examples

All write requests require:
```http
Authorization: Bearer <token>
Content-Type: application/json
```

Read routes (`GET /tasks`, `GET /tasks/{id}`, `GET /events`, `/openapi.json`, `/docs`) require no authorization token.

### 1. Register a Delivery Goal

Send `PUT /tasks/{task_id}` before dispatching work.

Example: `PUT /tasks/job_example_alpha`

```json
{
  "title": "Example notes for Alice",
  "task": "Prepare a short example note. Do not include private material.",
  "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
  "group_id": "group_example"
}
```

Responses:
- `201 Created`: The row is newly registered with `revision` 1, stored `status` `planned`, and screen state `not_started`.
- `200 OK`: Resending the exact same body returns the current row, including any subsequent progress edits, without resetting task status.
- `409 Conflict`: Submitting a different body for an existing id returns 409 and leaves the row unchanged.

### 2. Report Progress and Attempts

Send `PATCH /tasks/{task_id}` when work starts, when milestones are reached, or when subagents return.

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

Rules for patching:
- `expected_revision` and `report_key` are required.
- The same payload and `report_key` on this task returns the first receipt with its original status, including 404 and 409. A different payload needs a new key. A hashless legacy receipt cannot be replayed; send a new key.
- To advance to a new attempt (e.g., on retry or worker handoff), pass a new `attempt_id` alongside the current `expected_revision`. That attempt becomes active.
- If an attempt is active, subsequent patches must name it.
- Submitting an update for an attempt that is no longer active returns `409 Conflict` (`code: "stale_attempt"`).
- On receiving `409 Conflict`, fetch the current row (`GET /tasks/{task_id}`) to inspect the latest `revision` and active attempt, then formulate a new patch with a fresh `report_key`. Do not reuse an old attempt id after a handoff.

### 3. Acceptance and Completion

Only the main orchestrating thread may set a task to accepted (`status: "accepted"`):
- The main thread must first inspect and verify the expected deliverable (e.g., verifying `notes/example.md` or `https://example.com/results/alpha`).
- If an attempt failed, encountered unknowns, or produced partial work, the task must remain unfinished.
- Never mark a row `Done` simply because a subprocess exited or became quiet.

Example final patch:
```json
{
  "expected_revision": 2,
  "report_key": "report_example_2",
  "attempt_id": "attempt_example_1",
  "status": "accepted",
  "badges": [],
  "result_refs": [{"kind": "http", "value": "https://example.com/results/alpha", "label": "Example result"}]
}
```

### 4. Read Endpoints
- `GET /tasks/{task_id}`: Retrieves one task record.
- `GET /tasks`: Lists task rows and summary tallies (`count`, `not_started`, `in_progress`, `done`). Supports filters `group_id`, `status`, `ui_state`, `q`, and `include_cancelled`.
- `GET /events`: Subscribes to server-sent change hints. A hint signals the client to re-fetch `GET /tasks`.
- `/openapi.json` and `/docs`: Expose the service API specification.

### 5. Error Envelopes
Errors return a JSON object with `code` and `message`:
- `401 unauthorized`: Missing or invalid Bearer token.
- `404 not_found`: Unknown task id.
- `409 conflict` or `stale_attempt`: Concurrency violation or stale attempt identifier. Returns current row data.
- `422 validation_error`: Malformed request without echoing submitted values.
