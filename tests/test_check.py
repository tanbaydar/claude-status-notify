import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from watcher.check import (
    active_keyword_incidents,
    component_transitions,
    keyword_transitions,
    run,
    watched_components,
)


class WatcherTests(unittest.TestCase):
    def test_component_transitions_are_transition_only(self):
        down, up = component_transitions(
            {"claude.ai": "operational", "Claude Code": "major_outage"},
            {"claude.ai": "degraded_performance", "Claude Code": "operational"},
        )
        self.assertEqual(down, [("claude.ai", "degraded_performance")])
        self.assertEqual(up, ["Claude Code"])

    def test_unchanged_outage_does_not_notify(self):
        down, up = component_transitions(
            {"Claude Code": "major_outage"},
            {"Claude Code": "major_outage"},
        )
        self.assertEqual((down, up), ([], []))

    def test_design_is_found_in_incident_update(self):
        summary = {
            "incidents": [
                {
                    "id": "inc-1",
                    "name": "Elevated errors",
                    "status": "investigating",
                    "incident_updates": [
                        {"body": "Claude Code and Claude Design are affected."}
                    ],
                }
            ]
        }
        matches, titles = active_keyword_incidents(summary)
        self.assertEqual(matches["Claude Design"], ["inc-1"])
        self.assertEqual(titles["inc-1"], "Elevated errors")

    def test_resolved_design_incident_is_ignored(self):
        summary = {
            "incidents": [
                {
                    "id": "inc-1",
                    "name": "Claude Design outage",
                    "status": "resolved",
                }
            ]
        }
        matches, _ = active_keyword_incidents(summary)
        self.assertEqual(matches["Claude Design"], [])

    def test_design_recovery_when_incident_disappears(self):
        down, up = keyword_transitions(
            {"Claude Design": ["inc-1"]},
            {"Claude Design": []},
        )
        self.assertEqual(down, [])
        self.assertEqual(up, ["Claude Design"])

    def test_missing_component_is_unknown(self):
        components = watched_components({"components": []})
        self.assertEqual(components["claude.ai"], "unknown")

    def test_empty_committed_state_initializes_silently(self):
        summary = {
            "components": [
                {"name": "claude.ai", "status": "major_outage"},
                {"name": "Claude Code", "status": "operational"},
            ],
            "incidents": [],
        }
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                '{"components": {}, "keyword_incidents": {}, "checked_at": null}\n',
                encoding="utf-8",
            )
            with (
                patch("watcher.check.config.STATE_PATH", str(state_path)),
                patch("watcher.check.fetch_json", return_value=summary),
                patch("watcher.check.send_ntfy") as notify,
            ):
                self.assertEqual(run(), 0)
            notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
