#!/usr/bin/env python3
"""Poll Anthropic's status page and notify ntfy about transitions."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from watcher import config
except ModuleNotFoundError:  # Supports: python3 watcher/check.py
    import config  # type: ignore[no-redef]


OPERATIONAL = "operational"


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "claude-status-notify/1.0"},
    )
    with urlopen(request, timeout=config.HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read {path}: {error}") from error
    if not isinstance(state, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return state


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def watched_components(summary: dict[str, Any]) -> dict[str, str]:
    available = {
        item.get("name"): item.get("status", "unknown")
        for item in summary.get("components", [])
        if isinstance(item, dict)
    }
    # Missing components are explicit so a status-page schema/name change is
    # visible instead of being mistaken for a recovery.
    return {
        name: str(available.get(name, "unknown"))
        for name in config.WATCH_COMPONENTS
    }


def incident_text(incident: dict[str, Any]) -> str:
    updates = incident.get("incident_updates", [])
    update_text = " ".join(
        str(update.get("body", ""))
        for update in updates
        if isinstance(update, dict)
    )
    return f"{incident.get('name', '')} {update_text}".casefold()


def active_keyword_incidents(
    summary: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    matches = {service: [] for service in config.KEYWORD_SERVICES}
    titles: dict[str, str] = {}
    for incident in summary.get("incidents", []):
        if not isinstance(incident, dict) or incident.get("status") == "resolved":
            continue
        incident_id = str(incident.get("id", "")).strip()
        if not incident_id:
            continue
        text = incident_text(incident)
        titles[incident_id] = str(incident.get("name", "Active incident"))
        for service, keywords in config.KEYWORD_SERVICES.items():
            if any(keyword.casefold() in text for keyword in keywords):
                matches[service].append(incident_id)
    return matches, titles


def component_transitions(
    previous: dict[str, str], current: dict[str, str]
) -> tuple[list[tuple[str, str]], list[str]]:
    down: list[tuple[str, str]] = []
    recovered: list[str] = []
    for name, status in current.items():
        old_status = previous.get(name, OPERATIONAL)
        if old_status == OPERATIONAL and status != OPERATIONAL:
            down.append((name, status))
        elif old_status != OPERATIONAL and status == OPERATIONAL:
            recovered.append(name)
    return down, recovered


def keyword_transitions(
    previous: dict[str, list[str]], current: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    down: list[str] = []
    recovered: list[str] = []
    for service in config.KEYWORD_SERVICES:
        old_ids = set(previous.get(service, []))
        new_ids = set(current.get(service, []))
        if not old_ids and new_ids:
            down.append(service)
        elif old_ids and not new_ids:
            recovered.append(service)
    return down, recovered


def relevant_incident_titles(
    incident_ids: dict[str, list[str]], titles: dict[str, str]
) -> list[str]:
    ids = {incident_id for values in incident_ids.values() for incident_id in values}
    return sorted({titles[item] for item in ids if item in titles})


def send_ntfy(message: str, title: str, priority: str, tags: str) -> None:
    if not config.NTFY_TOPIC:
        raise RuntimeError(
            "NTFY_TOPIC is required when a status transition needs notification"
        )
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    request = Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
            "User-Agent": "claude-status-notify/1.0",
        },
    )
    with urlopen(request, timeout=config.HTTP_TIMEOUT_SECONDS):
        pass


def run() -> int:
    state_path = Path(config.STATE_PATH)
    try:
        summary = fetch_json(config.STATUS_URL)
        components = watched_components(summary)
        keyword_incidents, incident_titles = active_keyword_incidents(summary)
        previous = load_state(state_path)

        new_state = {
            "components": components,
            "keyword_incidents": keyword_incidents,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        if previous is None or not previous.get("components"):
            atomic_write_json(state_path, new_state)
            print("Initialized state; first run is intentionally silent.")
            return 0

        component_down, component_up = component_transitions(
            previous.get("components", {}), components
        )
        keyword_down, keyword_up = keyword_transitions(
            previous.get("keyword_incidents", {}), keyword_incidents
        )

        down_labels = [
            f"{name} ({status.replace('_', ' ')})"
            for name, status in component_down
        ] + keyword_down
        up_labels = component_up + keyword_up

        if down_labels:
            context = relevant_incident_titles(keyword_incidents, incident_titles)
            suffix = f"\nIncident: {'; '.join(context)}" if context else ""
            send_ntfy(
                f"DOWN: {', '.join(down_labels)}{suffix}",
                "Claude service alert",
                "high",
                "red_circle,warning",
            )
        if up_labels:
            send_ntfy(
                f"BACK UP: {', '.join(up_labels)}",
                "Claude service recovery",
                "default",
                "green_circle,white_check_mark",
            )

        # Commit the transition only after every required notification succeeds.
        # A failed POST will therefore be retried on the next run.
        atomic_write_json(state_path, new_state)
        print(
            f"Checked {len(components)} components; "
            f"{len(down_labels)} down transition(s), {len(up_labels)} recovery."
        )
        return 0
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
        print(f"Status check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
