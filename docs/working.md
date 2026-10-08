# Working Notes: agent-taskboard

Date: 2026-10-07

Verification: ruff passed. Unit pytest 39 passed, 2 deselected. SSE and browser were not rerun; those files were not changed in this pass. Private needle scan passed.

## Current Status
This draft establishes the architecture, requirements, API contracts, test plan, agent skill, and user interface labels for `agent-taskboard`.

## Decisions and Core Mechanics

1. **Service Boundaries**:
   - The service is an HTTP daemon and single-page web dashboard.
   - An AI writes task rows over HTTP. A person reads the board in a browser.
   - The dashboard contains no buttons to run, stop, retry, or approve tasks.
   - The service does not schedule or stop agents.
   - There is no task CLI.

2. **Data Model**:
   - One row represents one delivery goal.
   - Task identifier follows `job_example_alpha` and stays consistent across retries and handoffs.
   - Attempts follow `attempt_example_1` and fold under the row.
   - There is no parent-child task tree.
   - `group_example` acts as a sorting label rather than a hierarchical container.
   - Session links such as `opencode://session/ses_example` are pointers, not task identifiers.

3. **Screen States and Badges**:
   - Primary screen states: `Not started`, `In progress`, and `Done` (`Done` means accepted).
   - Diagnostic badges: `Waiting for review`, `Failed`, `Blocked`, `Not updated`, and `Unknown`.
   - A badge is not `Done`.
   - `Idle` is not a status.
   - A quiet process is not acceptance and is not failure.
   - Cancelled rows are omitted from the three summary counts (`not_started`, `in_progress`, `done`).
   - Inactivity beyond `AGENT_TASKBOARD_STALE_AFTER_SECONDS` (default: 1800s) displays `Not updated` on unaccepted rows. Accepted rows do not gain that badge because a report is old.

4. **Web Dashboard Experience**:
   - Supports pinning one group at the top while displaying all open rows on the same page.
   - Completed tasks are folded into a `Done` section.
   - Local paths are rendered as copyable text blocks rather than links.
   - Chinese characters in titles and goals are preserved without encoding loss.
   - Responsive layout readable on narrow screens.
   - Offline banner appears when connection is lost, preserving the last snapshot without marking rows failed.
   - `GET /events` delivers lightweight change hints that trigger a client re-fetch of `GET /tasks`.

5. **Security and Environment**:
   - Write requests require `Authorization: Bearer <token>`.
   - The token is read from the environment (`AGENT_TASKBOARD_TOKEN`) or a `.env` file in the working directory. Existing environment variables are never overwritten.
   - The service refuses startup if the token is missing or equals `replace-with-a-long-random-token`.
   - Default bind is `127.0.0.1` port `8765`. For a trusted LAN or Tailscale interface, the operator sets `AGENT_TASKBOARD_HOST=0.0.0.0` and may set `AGENT_TASKBOARD_PORT=8789`.
   - CORS is empty unless explicit `http` or `https` origins are configured. Wildcards (`*`) are disallowed.
   - The service does not download files. There is no artifact route.

## Standard Entities and Fixtures
- Persons: Alice, Bob
- Email addresses: alice@example.com, bob@example.net
- Identifiers: job_example_alpha, attempt_example_1, report_example_1, group_example
- URLs and paths: https://example.com/results/alpha, opencode://session/ses_example, notes/example.md

## Test Strategy Summary
- Unit tests: `python -m pytest`
- Isolated server tests: `python -m pytest -m integration -o addopts=`
- The reader is never instructed to start the service manually as part of unit test execution.
