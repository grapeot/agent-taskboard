#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "$#" -ne 0 ]; then
  echo "This service has no task subcommands. Set the environment, then run with no arguments." >&2
  exit 2
fi
if [ ! -d .venv ]; then
  echo "missing .venv; create it with: uv venv --python 3.12" >&2
  exit 1
fi
. .venv/bin/activate
exec python -m agent_taskboard
