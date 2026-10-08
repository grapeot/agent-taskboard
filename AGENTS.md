# AGENTS.md

Instructions for automated AI agents and developers working on or integrating with `agent-taskboard`.

Repository: https://github.com/grapeot/agent-taskboard
License: MIT
Default branch: master
Import name: agent_taskboard

## Operating Philosophy

- `agent-taskboard` is an HTTP service with a single-page web dashboard.
- An AI writes task rows over HTTP. A person reads a one-page board.
- The web page has no run, stop, retry, or approve buttons.
- The service does not schedule or stop agents.
- There is no task CLI. All task management occurs via HTTP requests.

## Setup and Verification Commands

Initialize the virtual environment and install dependencies:

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
cp .env.example .env
```

Replace the token placeholder locally. Do not print that value. Then start `python -m agent_taskboard` and read `/openapi.json`.

Start the service with `python -m agent_taskboard` and no arguments. A process launcher can start `python -m agent_taskboard` with the checkout as the working directory.

Run unit tests:
```bash
python -m pytest
```

Run isolated server integration tests:
```bash
python -m pytest -m integration -o addopts=
```

Do not tell the reader to start the service as part of unit tests. Unit test fixtures mock or manage their own test servers.

## Producer Rules for Caller Agents

Follow these rules in this exact order because later steps use earlier results:

1. Read the host AGENTS.md or CLAUDE.md and any routing file before editing discovery. If the host has rules/skills/INDEX.md or skills/INDEX.md, add a pointer to skills/agent-taskboard/SKILL.md. Otherwise add a short pointer in AGENTS.md or CLAUDE.md. Install only that one skill.
2. Keep the checkout and its .venv. Copy .env.example to .env and set a private token. Do not commit .env.
3. Start python -m agent_taskboard from that directory. Read /openapi.json before sending a body.
4. Create one job_ id and reuse it. PUT the goal and expected deliverable before dispatch.
5. PATCH when work starts, when something material changes, and when a child returns. Use a new report_key for each new report. Retry the same report with the same key.
6. On 409, read the current row and send a new report key. Do not reuse the old attempt id after a handoff.
7. The main thread sets accepted only after it has checked the deliverable. Failure, unknown, and partial work stay unfinished. Do not treat a quiet or idle runtime as Done.

## Data and State Contracts

### Tasks and Identifiers
- One row represents one delivery goal.
- The task identifier looks like `job_example_alpha` and remains unchanged across retries and handoffs.
- An attempt identifier looks like `attempt_example_1` and is folded under that row.
- There is no parent-child task tree.
- `group_example` is a label for sorting and filtering, not a hierarchy.
- Session links such as `opencode://session/ses_example` point to session transcripts; session links are not task ids.

### Screen States vs Badges
- Screen states are: `Not started`, `In progress`, `Done`.
- `Done` strictly means accepted.
- Diagnostic badges are: `Waiting for review`, `Failed`, `Blocked`, `Not updated`, and `Unknown`.
- A badge is not `Done`.
- `Idle` is not a status.
- A quiet process is not acceptance and is not failure.
- Cancelled rows are excluded from the three status counts (`not_started`, `in_progress`, `done`).
- When a row is not accepted and has not received a report within `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default 1800 seconds), it displays the `Not updated` badge. Accepted rows do not gain that badge when a report is old.

### Web Dashboard Behavior
- The page pins one group at the top, shows other open rows on the same page, and folds `Done`.
- Displays: title, goal, expected deliverable, state, last reported time, and result or session links.
- Search and filtering controls are on the page.
- A local path is rendered as text to copy, not as a link.
- Chinese text in task titles or goals must remain intact.
- The layout is responsive and readable on a narrow screen.
- When offline, the page reports the offline condition, preserves the last snapshot, and does not mark rows failed.
- The page never contains the token.

## Environment and Secrets

The service loads configuration from environment variables and an optional `.env` file in the working directory:
- `AGENT_TASKBOARD_HOST` (default: `127.0.0.1`)
- `AGENT_TASKBOARD_PORT` (default: `8765`)
- `AGENT_TASKBOARD_DB_PATH` (default: `./data/agent_taskboard.sqlite3`)
- `AGENT_TASKBOARD_TOKEN`
- `AGENT_TASKBOARD_CORS_ORIGINS`
- `AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS`
- `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default: `1800`)
- `AGENT_TASKBOARD_ENV_FILE` (default: `.env`)

The service reads the `.env` file itself and does not override variables already set in the execution environment. The service refuses to start if `AGENT_TASKBOARD_TOKEN` is missing or remains `replace-with-a-long-random-token`. Never put the token on a command line.

Setting `AGENT_TASKBOARD_HOST=0.0.0.0` or `AGENT_TASKBOARD_PORT=8789` is a local configuration choice for trusted LAN or Tailscale networks. CORS is empty unless the operator specifies explicit `http` or `https` origins. Never suggest `*`.

The service does not download files. There is no artifact route.

## API Examples

Use these exact examples for API calls:

### Register Task
`PUT /tasks/job_example_alpha`

```json
{
  "title": "Example notes for Alice",
  "task": "Prepare a short example note. Do not include private material.",
  "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
  "group_id": "group_example"
}
```

- Initial call returns `201`.
- Resending the exact same body returns `200` and returns the current row including subsequent edits without resetting status.
- Calling `PUT` with a different body for an existing id returns `409` and leaves the stored row unchanged.

### Patch Task Progress
`PATCH /tasks/job_example_alpha`

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

- Patches require `expected_revision` and `report_key`.
- `report_key` is scoped to the task id. The same payload replays the first receipt, including 404 and 409. A different payload for that pair is `409 idempotency_conflict`. The same key on another task is a separate report.
- A new attempt id with the current revision becomes the active attempt.
- Submitting an attempt id that is no longer active returns `409`.
- When an attempt is active, subsequent patches must specify it.

### Query Tasks and Events
- `GET /tasks/{task_id}`: Read one task row.
- `GET /tasks`: List task rows. Returns total `count`, plus `not_started`, `in_progress`, and `done` counts. Query parameters: `group_id`, `status`, `ui_state`, `q`, and `include_cancelled`.
- `GET /events`: Emits change hints. The browser uses this hint to trigger `GET /tasks`. A missed hint does not alter stored rows.

### Error Protocol
Standard error envelope:
```json
{
  "code": "validation_error",
  "message": "The request body does not match the typed body.",
  "fields": ["title"]
}
```

Codes:
- `401 unauthorized`
- `404 not_found`
- `409 conflict` or `stale_attempt` (returns current row)
- `422 validation_error` (without echoing submitted invalid values)

## Testing and Documentation Rules

- Use only standard mock entities: Alice, Bob, alice@example.com, bob@example.net, job_example_alpha, attempt_example_1, report_example_1, group_example, https://example.com/results/alpha, opencode://session/ses_example, notes/example.md.
- Never write home directories, absolute paths, or private workspace paths into documentation or code comments.
