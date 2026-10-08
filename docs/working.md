# Working Log

## 2026-10-07

- Created project scaffold for agent-taskboard.
- Added live GET /health endpoint reporting phase scaffold.
- Added static placeholder page served at GET /.
- Published typed task routes in OpenAPI schema returning 501 Not Implemented.
- Added configuration example and offline test specifications.

Verification: `python -m ruff check .` passed. `python -m pytest` passed, 24 tests. The service was not started.

### Lessons

- do not treat 501 as an empty board
- do not put the write token in HTML or email
- default bind is loopback
- do not copy private task text into this repo
