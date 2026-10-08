# Test Strategy and Coverage

This document outlines the testing scope for the agent-taskboard scaffold build.

## Offline Test Execution

Offline quality checks and test suites run with two commands:

```bash
python -m ruff check .
python -m pytest
```

Do not start the service as part of the test command. The test suite executes entirely in-process and offline.

## Coverage Areas

The automated test suite covers the following items:

1. **Package Import**: Verifies that the `agent_taskboard` module can be imported without missing dependencies or syntax errors.
2. **Health Route**: Verifies that `GET /health` returns status 200 with JSON payload reporting `{"phase": "scaffold"}`.
3. **OpenAPI Schema and Metadata**: Verifies that the in-process app publishes route summaries, descriptions, response codes, and field descriptions with examples. When the service is started, that schema is at `http://127.0.0.1:8765/openapi.json` and `http://127.0.0.1:8765/docs`. Pytest does not bind a port.
4. **Link Rejection**: Verifies that result links allow `http`, `https`, and `opencode://` (such as `https://example.com/results/alpha` and `opencode://session/ses_example`), while rejecting `javascript`, `data`, and `file` schemes.
5. **Three-State Projection**: Tests the tokens `not_started`, `in_progress`, and `done`. The page labels those Not started, In progress, and Done. Done means accepted. `waiting_review`, `failed`, `blocked`, and `stale` stay badges. `excluded` is cancelled and is outside the three-state count. Idle is not a status.
6. **Authentication versus 501 Stubs**: Verifies that `PUT` and `PATCH` without a valid bearer token return 401, and the same calls with a valid token return 501. Confirms that `GET /tasks`, `GET /events`, and `GET /artifacts/{artifact_id}` return 501 without a token, and without persisting records or opening a stream.
7. **No Database File Created**: Asserts that running tests or loading the scaffold produces no SQLite database file on disk.
8. **Public-File Hygiene**: Scans project assets to ensure no secret tokens, absolute filesystem paths, or personal user paths exist in committed files.

## Limitations in This Scaffold

No end-to-end board test exists yet because storage and SSE are not implemented.

## Manual Verification

Manual checks in this scaffold phase are limited to:

- `GET /health` returning JSON that includes `"phase": "scaffold"`
- `GET /` returning the static placeholder page
