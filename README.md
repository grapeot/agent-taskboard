# agent-taskboard

agent-taskboard is a small local HTTP service and read-only task board. An AI writes task rows over HTTP. A person reads them in a browser.

The intended public repository is https://github.com/grapeot/agent-taskboard. License: MIT. Default branch: master.

## What This Checkout Actually Does

This repository checkout is an initial scaffold.

- The Python package can be imported as `agent_taskboard`.
- `GET /health` is live and returns status 200. The JSON includes `"phase": "scaffold"`.
- `GET /` serves a static, read-only HTML placeholder page.
- Typed task routes are published in the OpenAPI schema at `http://127.0.0.1:8765/openapi.json` and `http://127.0.0.1:8765/docs`.
- `PUT` and `PATCH` need a bearer token. A valid token gets HTTP 501. A missing or wrong token gets HTTP 401. `GET /tasks`, `GET /events`, and `GET /artifacts/{artifact_id}` return 501 and do not use the write token.
- This build does not store tasks, stream events, or resolve files.

## What Is Not Built Yet

The following capabilities are reserved for a later implementation phase and are not operational in this scaffold:

- Task persistence to a SQLite database.
- Live Server-Sent Events (SSE) change hints via `GET /events`.
- Opaque artifact retrieval via `GET /artifacts/{artifact_id}`.
- Conflict detection and report key deduplication for `PUT` and `PATCH`.

In this build, `GET /tasks`, `PUT /tasks/{task_id}`, `PATCH /tasks/{task_id}`, `GET /events`, and `GET /artifacts/{artifact_id}` return HTTP 501 without storing or streaming anything.

## Service Architecture and Rules

The later implementation will run as a resident FastAPI service using Pydantic 2 models and a SQLite file (`./data/agent_taskboard.sqlite3`). It is not an in-memory toy and it is not a task CLI with subcommands. The start command is `python -m agent_taskboard` with no arguments.

- **Task Identity**: One row represents one delivery goal. Retries or agent handoffs keep the same task identifier (such as `job_example_alpha`) and fold the attempt (such as `attempt_example_1`) underneath. Session identifiers are distinct from task identifiers.
- **Read-Only Dashboard**: The page is strictly read-only. It has no run, stop, retry, or approve buttons. The service does not schedule, run, or kill agents.
- **Three Screen States Only**: `Not started`, `In progress`, and `Done`. Done means accepted.
- **Status Badges**: `Waiting for review`, `Failed`, `Blocked`, and `Stale` are badges displayed on top of the last known screen state. They are not a fourth screen state and they are not `Done`.
- **Process Activity**: Idle is not a status. A quiet process is not acceptance and is not failure.
- **Reporting Time**: The dashboard displays the last reported timestamp. A long gap means not updated; it does not mean done or failed.
- **Links and References**: Allowed URL schemes for result links are `http`, `https`, and `opencode://` (such as `https://example.com/results/alpha` and `opencode://session/ses_example`). The schemes `javascript`, `data`, and `file` are rejected. Local files are represented as plain text to copy or, later, as opaque artifact identifiers under configured roots (such as `notes/example.md`). There is no open directory browser.
- **Authentication**: Write calls require an `Authorization: Bearer <token>` header matching the server token. The HTML page must not contain that token. This build does not send email, and later notifications must not include the token.

## Network Choice

The default network bind is `127.0.0.1` port `8765`.

An operator may set `AGENT_TASKBOARD_HOST=0.0.0.0` to make the dashboard accessible over a trusted local area network (LAN) or a Tailscale interface. That is not a public-internet default. Serving the read-only page on a trusted LAN is a conscious choice by the operator.

## Configuration

Configuration is loaded from environment variables. Copy the provided `.env.example` file:

```bash
cp .env.example .env
```

Do not commit `.env`.

The service uses six environment variables:

1. `AGENT_TASKBOARD_HOST`: Bind address. Default is `127.0.0.1`.
2. `AGENT_TASKBOARD_PORT`: HTTP listen port. Default is `8765`.
3. `AGENT_TASKBOARD_DB_PATH`: Database file path for the later storage phase. Default is `./data/agent_taskboard.sqlite3`.
4. `AGENT_TASKBOARD_TOKEN`: Bearer token for write requests. Default placeholder is `replace-with-a-long-random-token`.
5. `AGENT_TASKBOARD_CORS_ORIGINS`: Allowed browser origins. Default is empty, meaning no extra browser origins. Do not configure wildcard origins (`*`).
6. `AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS`: Comma-separated directory paths for resolving opaque artifact identifiers in the later phase. Default is empty.

## Setup and Start

Run the following commands to install dependencies and start the service:

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m agent_taskboard
```

Run offline validation checks:

```bash
python -m ruff check .
python -m pytest
```

Do not start the service as part of the test command.

## Handing to Coding Agents

When handing the repository URL (`https://github.com/grapeot/agent-taskboard`) to Codex, Claude Code, Cursor, OpenCode, or another coding agent, instruct the agent to follow these steps:

1. Read the host `AGENTS.md` or `CLAUDE.md` and any routing files such as `WORKSPACE.md` before modifying discovery files.
2. If the host has `rules/skills/INDEX.md` or `skills/INDEX.md`, update that index with a reference to `skills/agent-taskboard/SKILL.md`. Otherwise add a short pointer in `AGENTS.md` or `CLAUDE.md`.
3. Expose only `skills/agent-taskboard/SKILL.md`. Do not install a second global skill. A private host overlay is not in this repository and is added by the host later, if the host uses one.
4. Keep the checkout and its `.venv`. Configure environment settings from `.env.example`, and do not commit `.env`.
5. Start the API and inspect `/openapi.json` before submitting request payloads.

## License

This project is licensed under the terms of the MIT license.
