"""Tests for the argparse CLI and the near-PI side effects it drives."""

import json
from unittest.mock import patch

import pytest

from watcher import __version__
from watcher.check import main, run, status_command


def _environment(components=None, incidents=None):
    return {
        "components": components or [],
        "incidents": incidents or [],
    }


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_status_command_prints_text(capsys):
    env = _environment(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "degraded_performance"},
        ]
    )
    with patch("watcher.check.fetch_json", return_value=env):
        assert status_command() == 0
    out = capsys.readouterr().out
    assert "claude.ai: operational" in out
    assert "Claude Code: degraded performance" in out


def test_status_command_json(capsys):
    env = _environment(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "operational"},
        ]
    )
    with patch("watcher.check.fetch_json", return_value=env):
        assert status_command(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["components"]["claude.ai"] == "operational"
    assert payload["components"]["Claude Code"] == "operational"
    assert payload["checked_at"]


def test_status_command_returns_1_on_fetch_failure(capsys):
    with patch(
        "watcher.check.fetch_json",
        side_effect=OSError("boom"),
    ):
        assert status_command() == 1
    assert "Status check failed" in capsys.readouterr().err


def test_main_routes_status():
    env = _environment(
        [{"name": "claude.ai", "status": "operational"}]
    )
    with (
        patch("watcher.check.fetch_json", return_value=env),
        patch("watcher.check.load_state", return_value=None),
    ):
        assert main(["--status"]) == 0


def test_dry_run_does_not_send_or_write_state(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "components": {
                    "claude.ai": "operational",
                    "Claude Code": "operational",
                },
                "keyword_incidents": {"Claude Design": []},
            }
        ),
        encoding="utf-8",
    )
    env = _environment(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "major_outage"},
        ]
    )
    with (
        patch("watcher.check.fetch_json", return_value=env),
        patch("watcher.check.send_ntfy") as notify,
    ):
        rc = run(dry_run=True, state_path=str(state_path))
    assert rc == 0
    notify.assert_not_called()
    # State must be untouched by a dry run.
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["components"]["Claude Code"] == "operational"


def test_dry_run_prints_notifications(capsys, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "components": {"claude.ai": "major_outage", "Claude Code": "operational"},
                "keyword_incidents": {"Claude Design": []},
            }
        ),
        encoding="utf-8",
    )
    env = _environment(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "operational"},
        ]
    )
    with patch("watcher.check.fetch_json", return_value=env):
        assert run(dry_run=True, state_path=str(state_path)) == 0
    out = capsys.readouterr().out
    assert "[dry-run] UP:" in out
    assert "claude.ai" in out


def test_failed_send_returns_1_and_does_not_commit_state(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "components": {
                    "claude.ai": "operational",
                    "Claude Code": "operational",
                },
                "keyword_incidents": {"Claude Design": []},
            }
        ),
        encoding="utf-8",
    )
    env = _environment(
        [
            {"name": "claude.ai", "status": "operational"},
            {"name": "Claude Code", "status": "major_outage"},
        ]
    )
    with (
        patch("watcher.check.fetch_json", return_value=env),
        patch("watcher.check.send_ntfy", side_effect=OSError("ntfy down")),
    ):
        rc = run(dry_run=False, state_path=str(state_path))
    assert rc == 1
    # State not committed, so the next cron run retries the notification.
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["components"]["Claude Code"] == "operational"
    assert "major_outage" not in written["components"].values()


def test_baseline_run_writes_state_and_stays_silent(tmp_path):
    state_path = tmp_path / "state.json"
    env = _environment(
        [{"name": "claude.ai", "status": "major_outage"}]
    )
    with (
        patch("watcher.check.fetch_json", return_value=env),
        patch("watcher.check.send_ntfy") as notify,
    ):
        assert run(dry_run=False, state_path=str(state_path)) == 0
    notify.assert_not_called()
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["components"]["claude.ai"] == "major_outage"
    assert written["checked_at"]


def test_main_supports_state_override(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    env = _environment(
        [{"name": "claude.ai", "status": "operational"}]
    )
    with (
        patch("watcher.check.fetch_json", return_value=env),
        patch("watcher.check.load_state", return_value=None),
    ):
        # --state is wired through to run(); a baseline run writes the file.
        rc = main(["--state", str(state_path)])
    assert rc == 0
    assert state_path.exists()


def test_corrupt_non_object_state_is_reported_not_crashed(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text("[1, 2, 3]", encoding="utf-8")  # JSON, but not an object
    env = _environment(
        [{"name": "claude.ai", "status": "operational"}]
    )
    with patch("watcher.check.fetch_json", return_value=env):
        rc = run(dry_run=False, state_path=str(state_path))
    assert rc == 1
    assert "must contain a JSON object" in capsys.readouterr().err