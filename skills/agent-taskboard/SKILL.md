---
name: agent-taskboard
description: Scaffold build for the agent-taskboard service. Task storage is not implemented in this checkout.
---

# agent-taskboard Skill

## Goal

Provide installation, operation, and verification guidance for agents integrating with the agent-taskboard service scaffold.

## Boundaries

- This checkout is a scaffold. Task persistence, event streaming, and artifact retrieval are not implemented.
- `GET /health` is live and reports phase `scaffold`.
- `GET /` serves a static placeholder page.
- Task routes are defined in OpenAPI but return HTTP 501 Not Implemented upon receipt of a valid Bearer token.
- The web interface is strictly read-only. The service does not run, schedule, or terminate agents.
- Expose only `skills/agent-taskboard/SKILL.md`. Do not install a second global skill. A private host overlay is not in this repository.

## Installation and Host Integration

When an agent receives the repository URL (`https://github.com/grapeot/agent-taskboard`), it must follow these steps:

1. Read the host `AGENTS.md` or `CLAUDE.md` and any routing files such as `WORKSPACE.md` before editing discovery files.
2. If the host has `rules/skills/INDEX.md` or `skills/INDEX.md`, update that index. Otherwise add a short pointer in `AGENTS.md` or `CLAUDE.md`.
3. Retain this checkout and its local virtual environment.
4. Copy `.env.example` to `.env` to configure local variables. Do not commit `.env`.

## Execution Commands

Set up and start the service with these commands and no others:

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

## Reading OpenAPI Schemas

Start the API and inspect the schema before sending request bodies:

- OpenAPI JSON: `http://127.0.0.1:8765/openapi.json`
- OpenAPI Docs: `http://127.0.0.1:8765/docs`

Callers must inspect `/openapi.json` and use the typed bodies. Write endpoints require `Authorization: Bearer <token>`.

In this scaffold build:
- Task routes return 501 after a valid token, or 401 if the write token is missing or wrong.
- `GET /tasks`, `GET /events`, and `GET /artifacts/{artifact_id}` return 501 without storing or streaming anything.

## Acceptance Checks

Agents validating this scaffold can apply the following checks:

1. Verify package import: `python -c "import agent_taskboard"` returns cleanly.
2. Verify linting and tests: `python -m ruff check .` and `python -m pytest` pass offline.
3. After a manual start, `curl http://127.0.0.1:8765/health` returns JSON that includes `"phase": "scaffold"`. Pytest does not listen on a port.
4. After a manual start, `curl http://127.0.0.1:8765/` returns the static placeholder HTML page.
5. After a manual start, a typed `PUT /tasks/job_example_alpha` with a valid token returns 501. Do not read that as an empty board.
6. Verify no disk database: Confirm no SQLite file is created on disk.

## What Not to Do

- Do not claim that the board stores tasks, runs agents, or provides live SSE updates.
- Do not create CLI subcommands; invocation is strictly `python -m agent_taskboard`.
- Do not commit `.env` or write tokens.
- Do not place the write token in HTML or email notifications.
- Do not interpret HTTP 501 responses as an empty task list.
- Do not allow wildcard CORS origins (`*`).
- Do not use `javascript`, `data`, or `file` URLs for links or artifacts.
