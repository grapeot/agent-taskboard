import json
import re
from pathlib import Path

import pytest

from agent_taskboard.models import ErrorBody, TaskListResponse, TaskPatchRequest, TaskRegisterRequest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "AGENTS.md", "docs/prd.md", "docs/rfc.md", "docs/test.md", "skills/agent-taskboard/SKILL.md")
FENCE = re.compile(r"```json\n(.*?)\n[ \t]*```", re.S)


def _blocks():
    found = []
    for rel in DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for match in FENCE.finditer(text):
            found.append((rel, match.group(1)))
    return found


def test_executable_json_matches_live_models():
    assert _blocks()
    for rel, raw in _blocks():
        payload = json.loads("\n".join(line[4:] if line.startswith("    ") else line for line in raw.splitlines()))
        if "expected_revision" in payload:
            TaskPatchRequest.model_validate(payload)
        elif {"title", "task", "expected_deliverable", "group_id"} <= set(payload):
            TaskRegisterRequest.model_validate(payload)
        elif "code" in payload:
            ErrorBody.model_validate(payload)
        elif "tasks" in payload and "count" in payload:
            TaskListResponse.model_validate(payload)
        else:
            pytest.fail(f"unclassified executable json in {rel}")
