import pytest
from pydantic import ValidationError

from agent_taskboard.models import ResultLink


def test_allowed_links():
    http = ResultLink(kind="http", value="https://example.com/results/alpha", label="Example result")
    assert http.kind == "http"
    session = ResultLink(kind="opencode", value="opencode://session/ses_example", label="Example session")
    assert session.value.startswith("opencode://")
    copied = ResultLink(kind="copy_path", value="notes/example.md", label="Example note")
    assert copied.kind == "copy_path"


@pytest.mark.parametrize(
    "kind,value",
    [
        ("http", "javascript:alert(1)"),
        ("http", "data:text/html,hi"),
        ("http", "file:///tmp/example"),
        ("http", "vbscript:msg"),
        ("opencode", "javascript:alert(1)"),
        ("copy_path", "javascript:alert(1)"),
        ("copy_path", "../secret"),
        ("http", "https://alice:secret@example.com/results/alpha"),
    ],
)
def test_rejected_links(kind, value):
    with pytest.raises(ValidationError):
        ResultLink(kind=kind, value=value, label="bad")
