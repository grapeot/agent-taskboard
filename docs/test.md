# Test Plan and Verification Guide

This document specifies the verification strategy, test suites, and execution commands for `agent-taskboard`.

## Test Execution Commands

Run unit tests:
```bash
python -m pytest
```

Run isolated server integration tests:
```bash
python -m pytest -m integration -o addopts=
```

Do not tell the reader to start the service as part of unit tests. Unit test fixtures instantiate test clients or manage isolated background servers automatically.

## Test Data Fixtures

All tests use standardized fake entities:
- Persons and Emails: `Alice`, `Bob`, `alice@example.com`, `bob@example.net`
- Task Identifier: `job_example_alpha`
- Attempt Identifier: `attempt_example_1`
- Report Key: `report_example_1`
- Group Identifier: `group_example`
- Deliverable URLs: `https://example.com/results/alpha`
- Session Transcripts: `opencode://session/ses_example`
- Local Deliverable Paths: `notes/example.md`

## Test Suites and Verification Areas

### 1. Configuration and Startup Verification
- **Environment Variable Precedence**: Confirm variables defined in the host environment take precedence over variables in `.env`.
- **Environment File Loading**: Verify the service loads configuration from `.env` in the working directory (or from `AGENT_TASKBOARD_ENV_FILE`) without overwriting existing process variables.
- **Token Validation**:
  - Verify startup fails when `AGENT_TASKBOARD_TOKEN` is unset or empty.
  - Verify startup fails when `AGENT_TASKBOARD_TOKEN` is set to `replace-with-a-long-random-token`.
- **CORS Origin Validation**:
  - Verify explicit origins (e.g., `http://localhost:3000,https://example.com`) are parsed correctly.
  - Verify wildcard `*` is rejected during configuration parsing.
- **Network Interface Defaults**: Verify default host binds to `127.0.0.1` and port to `8765`, with override capability for `AGENT_TASKBOARD_HOST=0.0.0.0` and `AGENT_TASKBOARD_PORT=8789`.

### 2. Task Registration (`PUT /tasks/{task_id}`)
- **Initial Registration (201 Created)**:
  - Submit `PUT /tasks/job_example_alpha` with:
    ```json
    {
      "title": "Example notes for Alice",
      "task": "Prepare a short example note. Do not include private material.",
      "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
      "group_id": "group_example"
    }
    ```
  - Verify response code is `201 Created`.
  - Verify stored status is `planned`, revision is 1, and screen state is `not_started`.
- **Idempotent Re-registration (200 OK)**:
  - Resubmit the exact same body to an existing task ID.
  - Verify response code is `200 OK`.
  - Verify the returned record contains the current state and revision, preserving any progress edits made after initial registration.
  - Verify stored status is not reset to `planned`.
- **Conflicting Registration (409 Conflict)**:
  - Submit a `PUT` request with differing title, task, or deliverable for an existing ID.
  - Verify response code is `409 Conflict`.
  - Verify the stored row in the database remains unchanged.

### 3. Progress Updates and Concurrency (`PATCH /tasks/{task_id}`)
- **Report Key Idempotency**:
  - Send a `PATCH` request with `report_key: "report_example_1"`.
  - Send a second `PATCH` request with the same `report_key` but a conflicting revision.
  - Verify the second call returns the first receipt immediately with `200 OK` without checking revision.
- **Optimistic Concurrency Control**:
  - Submit a `PATCH` request where `expected_revision` does not match the stored revision.
  - Verify the server returns `409 Conflict` containing the current task row.
- **Active Attempt Tracking**:
  - Submit a patch introducing a new `attempt_id` alongside the matching revision.
  - Verify the new attempt becomes the active attempt.
  - Submit a patch referencing an attempt that is no longer active.
  - Verify response code is `409 Conflict` with `code: "stale_attempt"`.
  - When an attempt is active, verify patches omitting the active attempt identifier are rejected.

### 4. Screen States, Badges, and Staleness
- **Screen States Mapping**:
  - stored `status` `planned` maps to screen state `not_started`.
  - stored `status` `in_progress` maps to screen state `in_progress`.
  - stored `status` `accepted` maps to screen state `done`. Done means accepted.
- **Badge Derivation**:
  - Verify badges: `Waiting for review`, `Failed`, `Blocked`, `Not updated`, `Unknown`.
  - Verify a badge is not `Done`.
  - Verify `Idle` is not a status.
  - Verify a quiet process is not treated as acceptance and not treated as failure.
- **Stale Report Window**:
  - Set `AGENT_TASKBOARD_STALE_AFTER_SECONDS=1800`.
  - Create a task in `in_progress` status with `last_reported_at` older than 1800 seconds.
  - Verify the task presents the `Not updated` badge.
  - Mark the task accepted (`status: "accepted"`).
  - Verify accepted rows do not gain the `Not updated` badge because a report is old.
- **Cancelled Tasks**:
  - Verify cancelled tasks are omitted from the default list and from the three screen-state counts. With `include_cancelled=true` they appear in `count` but still not in those three counts.
  - Verify cancelled tasks are omitted from `tasks` list unless `include_cancelled=true` is requested.

### 5. UTF-8 and Field Rendering
- **Unicode Preservation**:
  - Create tasks with Chinese characters in `title` and `task`.
  - Verify text round-trips through SQLite and JSON serialization without mangling.
- **Local Path Handling**:
  - Provide a local path such as `notes/example.md` as a `copy_path` result ref.
  - Verify the dashboard renders it as text to copy, not as an active HTTP hyperlink.
- **Session and Result Links**:
  - Provide `opencode://session/ses_example` or `https://example.com/results/alpha`.
  - Verify valid URI schemes render as clickable links.

### 6. Security and Error Handling
- **Write Route Authentication**:
  - Verify `PUT` and `PATCH` requests without `Authorization: Bearer <token>` return `401 unauthorized`.
  - Verify requests with an incorrect token return `401 unauthorized`.
- **Read Route Access**:
  - Verify `GET /tasks`, `GET /tasks/{id}`, and `GET /events` require no token.
- **Input Validation (422 validation_error)**:
  - Submit invalid payloads (e.g., non-integer revision, missing required fields).
  - Verify response returns code `validation_error` and a message explaining the rule without echoing the submitted invalid value.
- **Token Boundary in UI**:
  - Inspect served HTML, CSS, and JS assets at `GET /`.
  - Verify the authentication token is never rendered or bundled into client code.
- **No File Downloads**:
  - Verify the service exposes no artifact download route.

### 7. Isolated Server Integration Tests
Run via:
```bash
python -m pytest -m integration -o addopts=
```
- Tests spin up an isolated server bound to an ephemeral port with an in-memory or temporary SQLite database.
- Verifies Server-Sent Events stream (`GET /events`):
  - Client connects to `/events`.
  - Client sends `PUT /tasks/job_example_alpha`.
  - Client receives a `change` event whose data includes `task_id`, `revision`, and `event_id`.
  - Client verifies that a missed hint does not corrupt or alter stored database rows.
- Verifies offline dashboard behavior:
  - When connection is severed, UI displays offline banner and maintains last snapshot without marking tasks failed.
