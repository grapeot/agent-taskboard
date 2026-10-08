# agent-taskboard

agent-taskboard provides a single-page task board for human oversight of autonomous AI work. An AI writes task rows over HTTP. A person reads the board in a web browser. The page has no run, stop, retry, or approve buttons. The service does not schedule or stop agents. There is no task CLI.

Public repository: https://github.com/grapeot/agent-taskboard
License: MIT
Default branch: master
Import name: agent_taskboard

## What the Service Does

- Exposes an HTTP API for registering and updating task rows.
- Serves a self-contained one-page web dashboard.
- Organizes work by delivery goal rather than execution steps.
- Tracks attempts under each row without constructing a task hierarchy.
- Sends live change hints to connected browsers via server-sent events.

## Data Model

- **Task row**: Represents one delivery goal. The identifier looks like `job_example_alpha` and stays the same across retries and handoffs.
- **Attempts**: Each run or execution cycle produces an attempt identifier such as `attempt_example_1`, folded under the corresponding task row.
- **Grouping**: `group_example` is a pin label, not a badge filter and not a parent task.
- **Session links**: Reference links such as `opencode://session/ses_example` point to agent transcripts or sessions. Session links are not task ids.

## Screen States and Badges

The board displays three screen states:
- `Not started`
- `In progress`
- `Done` (`Done` means accepted)

Rows may also carry diagnostic badges:
- `Waiting for review`
- `Failed`
- `Blocked`
- `Not updated`
- `Unknown`

Rules governing states and badges:
- A badge is not `Done`.
- `Idle` is not a status.
- A quiet process is not acceptance and is not failure.
- Cancelled rows are excluded from open task counts (`not_started`, `in_progress`, `done`).
- When a row is not accepted and receives no report within `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default 1800 seconds), the board displays `Not updated`.
- Accepted rows never gain the `Not updated` badge when a report is old.

## Web Dashboard

The one-page board provides:
- Pinned group view at the top of the page.
- Other open rows visible on the same page.
- Folded section for `Done` tasks.
- Row details: title, goal, expected deliverable, state, last reported time, and result or session links.
- The page has text search, a screen-state filter, and a pin that sorts one group above the other open rows. It does not filter by badge.
- Copyable text for local paths (rendered as plain text to copy, not clickable links).
- Full preservation of Chinese text in task titles and goals.
- Responsive layout readable on narrow mobile and desktop viewports.
- Offline status indicator: when the browser loses network connection, the page displays an offline banner, retains the last snapshot, and avoids marking tasks failed.

The web page never contains the authentication token.

## Setup and Installation

Requirements: Python 3.12 and uv.

Read the host `AGENTS.md` or `CLAUDE.md` and any routing file first. Clone https://github.com/grapeot/agent-taskboard to a persistent checkout, and point the host skill index at that checkout's `skills/agent-taskboard/SKILL.md`. Do not assume the host skills directory is this repository.

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
cp .env.example .env
```

Replace `replace-with-a-long-random-token` in `.env` with a random value generated on that machine. Do not print the token or commit `.env`.

```bash
python -m agent_taskboard
```

Then read `http://127.0.0.1:8765/openapi.json`. `scripts/start.sh` only activates the checkout virtualenv and runs that module. It does not load `.env` itself. A process launcher can use the same command with the checkout as the working directory.

## Configuration

The service reads configuration from environment variables and from a `.env` file located in the working directory. Variables already set in the server environment are not overridden.

The service refuses to start if `AGENT_TASKBOARD_TOKEN` is missing or still set to the placeholder `replace-with-a-long-random-token`. Do not put the token on a command line.

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `AGENT_TASKBOARD_HOST` | `127.0.0.1` | Network interface to bind. Use `0.0.0.0` for a trusted LAN or Tailscale. |
| `AGENT_TASKBOARD_PORT` | `8765` | TCP port to listen on. An operator may set `8789` for LAN access. |
| `AGENT_TASKBOARD_DB_PATH` | `./data/agent_taskboard.sqlite3` | Relative path to the SQLite database file. |
| `AGENT_TASKBOARD_TOKEN` | *None* | Shared secret for HTTP Bearer authentication on write routes. |
| `AGENT_TASKBOARD_CORS_ORIGINS` | *Empty* | Comma-separated list of explicit `http` or `https` origins. Never use `*`. |
| `AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS` | *Empty* | Reserved and unused in this version. A local result is `copy_path` text, not a file-access check. |
| `AGENT_TASKBOARD_STALE_AFTER_SECONDS` | `1800` | Inactivity threshold before an unaccepted task shows `Not updated`. |
| `AGENT_TASKBOARD_ENV_FILE` | `.env` | Relative path to an environment file to load on startup. |

Network notes:
- Default bind is `127.0.0.1` port `8765`. Binding to `0.0.0.0` or port `8789` is a local configuration choice for trusted networks, not a public deployment.
- CORS is empty by default unless explicit origins are configured.
- The service does not download files. There is no artifact route.

## API Overview

Write routes require an `Authorization: Bearer <token>` header. Read routes are unauthenticated for local viewer access. OpenAPI documentation is served at `/openapi.json` and `/docs`.

### Register a Task
`PUT /tasks/job_example_alpha`

Request body:
```json
{
  "title": "Example notes for Alice",
  "task": "Prepare a short example note. Do not include private material.",
  "expected_deliverable": "A markdown note whose example link is https://example.com/results/alpha.",
  "group_id": "group_example"
}
```

- First call returns `201 Created`.
- Repeating the exact same body returns `200 OK` and returns the current row, including any subsequent edits, without resetting task status.
- Calling `PUT` with a different body for an existing id returns `409 Conflict` and leaves the stored row unchanged.

### Report Progress
`PATCH /tasks/job_example_alpha`

Patches require `expected_revision` and `report_key`.
- `report_key` is scoped to that task. The same payload returns the first receipt. A different payload needs a new key.
- Introducing a new attempt identifier with the current revision makes it the active attempt.
- Submitting an attempt identifier that is no longer active returns `409 Conflict`.
- When an attempt is active, subsequent patches must name it.

### Read Tasks
- `GET /tasks/{task_id}`: Retrieves one task row by identifier.
- `GET /tasks`: Lists rows. `count` is the number of returned rows. `counts` has `not_started`, `in_progress`, and `done`. Cancelled rows are omitted unless `include_cancelled=true`, and they stay outside those three counts. Filters are `group_id`, `status`, `ui_state`, and `q`.

### Live Events
- `GET /events`: Server-sent event stream emitting change hints. It is a change notification signal, not an audit log. The browser re-fetches `GET /tasks` on initial load, on reconnect, and after receiving a hint. Missed hints do not alter server state.

### Error Format
Errors return a standard JSON object containing `code` and `message`:
- `401 unauthorized`: Missing or invalid Bearer token.
- `404 not_found`: Requested task row does not exist.
- `409 conflict` or `stale_attempt`: Revision mismatch or outdated attempt identifier. The current row state is included in the response.
- `422 validation_error`: Malformed payload. The response describes the error without echoing submitted values.

## Tests

Run unit tests:
```bash
python -m pytest
```

Run isolated server integration tests:
```bash
python -m pytest -m integration -o addopts=
```

Do not start the service manually when running unit tests.
