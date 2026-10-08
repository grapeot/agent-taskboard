import pytest

from agent_taskboard.models import Badge, TaskStatus, UiState, project_ui_state, validate_status_badges


def test_idle_is_not_a_status_or_done():
    assert "idle" not in {item.value for item in TaskStatus}
    assert "idle" not in {item.value for item in Badge}
    assert project_ui_state(TaskStatus.accepted, []) == UiState.done
    assert project_ui_state(TaskStatus.in_progress, [Badge.waiting_review]) == UiState.in_progress
    assert project_ui_state(TaskStatus.in_progress, [Badge.failed]) == UiState.in_progress
    assert project_ui_state(TaskStatus.planned, [Badge.blocked]) == UiState.not_started
    assert project_ui_state(TaskStatus.cancelled, []) == UiState.excluded


def test_accepted_does_not_decay():
    with pytest.raises(ValueError):
        validate_status_badges(TaskStatus.accepted, [Badge.stale])
    with pytest.raises(ValueError):
        validate_status_badges(TaskStatus.planned, [Badge.waiting_review])
