# Request for Comments: System Design and Contract

## 1. System Roles and Scope

agent-taskboard provides one board for delivery goals. An AI writes the rows. A person reads them.

- **Producer**: AI agents (such as Codex, Claude Code, Cursor, or OpenCode) sending typed HTTP updates.
- **Consumer**: A read-only web page accessed by a human operator in a browser.

*Scaffold status*: This checkout is a scaffold. It provides an importable Python package `agent_taskboard`. `GET /health` is live and returns phase `scaffold`. `GET /` serves a static placeholder page. The typed task routes are published in the OpenAPI schema but return 501 Not Implemented. This build does not persist tasks, stream events, or resolve artifacts.

## 2. Storage Architecture

- **Current Build**: No task store. Nothing is kept in memory or on disk. No database file is opened or created.
- **Later Phase**: A resident FastAPI service with Pydantic 2 models and a SQLite database located at `AGENT_TASKBOARD_DB_PATH` (`./data/agent_taskboard.sqlite3`). It is not an in-memory ephemeral store and not a task CLI with subcommands. The service starts via `python -m agent_taskboard` without command-line arguments.

## 3. Task Identity and Row Structure

- **One Row per Delivery Goal**: A row represents a single delivery objective identified by a task identifier such as `job_example_alpha`. It can belong to a group such as `group_example` and involve users such as Alice (`alice@example.com`) and Bob (`bob@example.net`).
- **Folding Attempts**: Retries, revisions, or agent handoffs keep the same task identifier and fold attempts (for example, `attempt_example_1`) underneath the parent goal.
- **Session Separation**: Agent session identifiers (for example `opencode://session/ses_example`) are distinct from task identifiers.

## 4. Mutation Contract and Conflict Resolution

*Note: The behaviors below describe the contract that the later phase will honor. This scaffold build does not execute these operations; endpoints return 501.*

- **PUT /tasks/{task_id}**:
  - Registers a task goal.
  - If a client repeats the exact same body for an existing task, the call succeeds idempotently and does not overwrite subsequent updates.
  - If a client sends a different body for an existing task identifier, the server returns HTTP 409 Conflict.
  - *Scaffold status: Not executed; returns 501.*
- **PATCH /tasks/{task_id}**:
  - Updates progress, state, or metadata.
  - The request payload carries `expected_revision` and `report_key` (such as `report_example_1`).
  - Idempotency check: If `report_key` matches an already recorded report, the server returns the previous receipt immediately without evaluating revision conflicts.
  - Revision check: If `report_key` is new and `expected_revision` does not match the database state, the server returns HTTP 409 Conflict.
  - Late attempt handling: A late attempt returning after a subsequent attempt has started receives HTTP 409 and is prevented from closing or overwriting the newer attempt.
  - *Scaffold status: Not executed; returns 501.*

## 5. State Projection and Display Rules

The consumer interface applies strict projection rules:

- **Three Screen States Only**:
  - `Not started`
  - `In progress`
  - `Done` (Done means accepted)
- **Status Badges**:
  - `Waiting for review`, `Failed`, `Blocked`, and `Stale` are badges displayed on top of the last known screen state.
  - Badges do not create a fourth screen state and are not equivalent to `Done`.
  - Idle is not a status. A quiet process is not acceptance and is not failure.
- **Timestamp Display**:
  - The interface displays the last reported timestamp.
  - A long gap between updates indicates that the task has not been updated. It does not indicate that the task is completed or failed.
- **Read-Only Interface**:
  - The dashboard contains no run, stop, retry, or approve buttons.
  - The service does not start, stop, or kill agent processes.

## 6. Links and Artifact Handling

- **Allowed Links**: Links associated with results or sessions must use `http`, `https`, or `opencode://` schemes (such as `https://example.com/results/alpha` or `opencode://session/ses_example`).
- **Rejected Schemes**: URIs using `javascript`, `data`, or `file` are rejected with HTTP 422.
- **Local Files and Artifacts**: Local file references are represented as plain text paths (such as `notes/example.md`) or resolved as opaque artifact identifiers.
- **GET /artifacts/{artifact_id}**:
  - In the later phase, this endpoint resolves only opaque identifiers within roots defined by `AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS`.
  - Raw filesystem paths are never accepted.
  - The service does not provide an open directory browser.
  - *Scaffold status: Not executed; returns 501.*

## 7. Event Notifications

- **GET /events**:
  - In the later phase, this endpoint will provide Server-Sent Events (SSE) acting as change hints rather than an event replay log.
  - When the web client receives a change hint, it re-fetches the current task snapshot via `GET /tasks`.
  - *Scaffold status: Not executed; returns 501.*

## 8. Network and Authorization Policy

- **Default Network Binding**: Binds to `127.0.0.1` on port `8765`.
- **Trusted LAN / Tailscale**: An operator may configure `AGENT_TASKBOARD_HOST=0.0.0.0` for access across a private LAN or Tailscale. Exposing the read-only dashboard to a trusted local network is a conscious operational choice, not a public internet default.
- **CORS Policy**: `AGENT_TASKBOARD_CORS_ORIGINS` defaults to empty, preventing external origins from querying the API. Wildcard origins (`*`) must not be configured.
- **Authentication**:
  - Write requests (`PUT`, `PATCH`) must supply `Authorization: Bearer <AGENT_TASKBOARD_TOKEN>`.
  - Read routes do not use the write token. The page cannot call a token-gated read without embedding the secret.
  - In this scaffold, valid write tokens yield 501, while missing or incorrect write tokens yield 401. Reads yield 501 with no token.
  - The web page must not contain the write token.
  - The service does not send emails in this build, and future notification systems must not include the write token.
