"""Tests for the pure run-plan decision logic (no network, disk, or ntfy)."""

from watcher.check import Notification, build_plan


def _summary(components=None, incidents=None):
    return {
        "components": components or [],
        "incidents": incidents or [],
    }


def test_baseline_plan_when_no_previous_state():
    plan = build_plan(
        _summary(
            [
                {"name": "claude.ai", "status": "major_outage"},
                {"name": "Claude Code", "status": "operational"},
            ]
        ),
        None,
    )
    assert plan.baseline is True
    assert plan.notifications == []
    assert plan.components["claude.ai"] == "major_outage"


def test_baseline_plan_when_snapshot_cleared():
    previous = {"components": {}, "keyword_incidents": {}}
    plan = build_plan(
        _summary(
            [
                {"name": "claude.ai", "status": "operational"},
                {"name": "Claude Code", "status": "operational"},
            ]
        ),
        previous,
    )
    assert plan.baseline is True
    assert plan.notifications == []


def test_down_transition_produces_high_priority_alert():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "operational",
        },
        "keyword_incidents": {},
    }
    summary = _summary(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "major_outage"},
        ]
    )
    plan = build_plan(summary, previous)
    assert plan.baseline is False
    assert len(plan.notifications) == 1
    (notification,) = plan.notifications
    assert notification.kind == "down"
    assert notification.priority == "high"
    assert "Claude Code (major outage)" in notification.message


def test_recovery_produces_default_priority_message():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "major_outage",
        },
        "keyword_incidents": {},
    }
    summary = _summary(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "operational"},
        ]
    )
    plan = build_plan(summary, previous)
    assert len(plan.notifications) == 1
    (notification,) = plan.notifications
    assert notification.kind == "up"
    assert notification.priority == "default"
    assert "Claude Code" in notification.message


def test_no_change_means_no_notifications():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "major_outage",
        },
        "keyword_incidents": {"Claude Design": []},
    }
    summary = _summary(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "major_outage"},
        ]
    )
    plan = build_plan(summary, previous)
    assert plan.notifications == []


def test_keyword_incident_triggers_down_and_includes_context():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "operational",
        },
        "keyword_incidents": {"Claude Design": []},
    }
    summary = _summary(
        incidents=[
            {
                "id": "inc-9",
                "name": "Claude Design issue",
                "status": "investigating",
                "incident_updates": [
                    {"body": "Claude Design is degraded."}
                ],
            }
        ]
    )
    plan = build_plan(summary, previous)
    assert len(plan.notifications) == 1
    (notification,) = plan.notifications
    assert notification.kind == "down"
    assert "Claude Design" in notification.message
    assert "Claude Design issue" in notification.message


def test_keyword_recovery_when_incident_resolves():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "operational",
        },
        "keyword_incidents": {"Claude Design": ["inc-1"]},
    }
    summary = _summary(
        components=[
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "operational"},
        ],
        incidents=[
            {"id": "inc-1", "name": "X", "status": "resolved"}
        ],
    )
    plan = build_plan(summary, previous)
    assert len(plan.notifications) == 1
    (notification,) = plan.notifications
    assert notification.kind == "up"
    assert "Claude Design" in notification.message


def test_notifications_are_dataclasses_with_ntfy_fields():
    previous = {
        "components": {
            "claude.ai": "operational",
            "Claude Code": "operational",
        },
        "keyword_incidents": {},
    }
    plan = build_plan(
        _summary(
            [
                {"name": "claude.ai", "status": "operational"},
                {"name": "Claude Code", "status": "degraded_performance"},
            ]
        ),
        previous,
    )
    assert isinstance(plan.notifications[0], Notification)
    assert plan.notifications[0].tags == "red_circle,warning"