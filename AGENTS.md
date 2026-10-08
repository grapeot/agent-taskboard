# Agent Guidelines for agent-taskboard

This repository is the scaffold for agent-taskboard, a local HTTP task board. An AI writes rows. A person reads them. This checkout does not store tasks.

## Commands

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

Do not start the service as part of the test command. Testing runs entirely in-process and offline. `scripts/start.sh` is a thin wrapper around `python -m agent_taskboard` and takes no arguments.

## Repository Layout

```
.
|-- AGENTS.md
|-- README.md
|-- LICENSE
|-- pyproject.toml
|-- .env.example
|-- .gitignore
|-- docs/
|   |-- prd.md
|   |-- rfc.md
|   |-- test.md
|   \-- working.md
|-- skills/
|   \-- agent-taskboard/
|       \-- SKILL.md
|-- scripts/
|   \-- start.sh          # optional wrapper; the module takes no task subcommands
|-- src/
|   \-- agent_taskboard/  # package, including static/index.html
|-- tests/
\-- .github/workflows/ci.yml
```

## Public Repository Rules

This project is prepared for the public repository at https://github.com/grapeot/agent-taskboard under the MIT license.

- **Default Git Branch**: The default branch is `master`, not `main`.
- **Git Operations**: Do not run `git init`, `git commit`, or `git push` unless the user explicitly asks.
- **Scaffold Status**: Do not claim that the board stores tasks or listens to live events. In this checkout, task routes return HTTP 501.
- **Privacy and Sanitization**: Do not write real secrets, private tokens, host environments, or machine-specific locations into files.
- **Permitted Mock Entities**: Use only standard placeholder identities: Alice, Bob, `alice@example.com`, `bob@example.net`, `job_example_alpha`, `attempt_example_1`, `report_example_1`, `group_example`, `https://example.com/results/alpha`, `opencode://session/ses_example`, and `notes/example.md`.
