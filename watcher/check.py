#!/usr/bin/env python3
"""Poll Anthropic's status page and notify ntfy about transitions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from watcher import __version__, config
except ModuleNotFoundError:  # Supports: python3 watcher/check.py
    import config  # type: ignore[no-redef]

    __version__ = "0.0.0"


OPERATIONAL = "operational"


@dataclass
class Notification:
    """A single ntfy push that a run may emit.

    ``kind`` is ``"down"`` or ``"up"`` and is used only for human-readable
    ``--dry-run`` output. Real sends use the ntfy fields below.
    """

    kind: str
    message: str
    title: str
    priority: str
    tags: str


@dataclass
class Plan:
    """What a run would do, decoupled from the side effects of doing it.

    Keeping the decision logic pure (no network, no disk, no ntfy) makes it
    trivially testable and lets ``--dry-run`` report exactly what a real run
    would ship without touching state or ntfy.
    """

    baseline: bool
    notifications: list[Notification] = field(default_factory=list)
    components: dict[str, str] = field(default_factory=dict)
    keyword_incidents: dict[str, list[str]] = field(default_factory=dict)
    incident_titles: dict[str, str] = field(default_factory=dict)


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
        raise TypeError(f"{path} must contain a JSON object")
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


def build_plan(summary: dict[str, Any], previous: dict[str, Any] | None) -> Plan:
    """Decide what a run should do, without performing any side effect."""
    components = watched_components(summary)
    keyword_incidents, incident_titles = active_keyword_incidents(summary)

    plan = Plan(
        baseline=False,
        components=components,
        keyword_incidents=keyword_incidents,
        incident_titles=incident_titles,
    )

    # First observation (or a cleared snapshot) is the baseline: record it and
    # stay silent so the next run only fires on real transitions.
    if previous is None or not previous.get("components"):
        plan.baseline = True
        return plan

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
        plan.notifications.append(
            Notification(
                kind="down",
                message=f"DOWN: {', '.join(down_labels)}{suffix}",
                title="Claude service alert",
                priority="high",
                tags="red_circle,warning",
            )
        )
    if up_labels:
        plan.notifications.append(
            Notification(
                kind="up",
                message=f"BACK UP: {', '.join(up_labels)}",
                title="Claude service recovery",
                priority="default",
                tags="green_circle,white_check_mark",
            )
        )
    return plan


def new_state_for(plan: Plan) -> dict[str, Any]:
    return {
        "components": plan.components,
        "keyword_incidents": plan.keyword_incidents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


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


def run(
    *,
    dry_run: bool = False,
    state_path: str | None = None,
) -> int:
    path = Path(state_path) if state_path else Path(config.STATE_PATH)
    try:
        summary = fetch_json(config.STATUS_URL)
        previous = load_state(path)
        plan = build_plan(summary, previous)

        if plan.baseline:
            atomic_write_json(path, new_state_for(plan))
            print("Initialized state; first run is intentionally silent.")
            return 0

        if dry_run:
            if plan.notifications:
                for notification in plan.notifications:
                    print(
                        f"[dry-run] {notification.kind.upper()}: "
                        f"{notification.message}"
                    )
            else:
                print("No transitions; a real run would stay quiet.")
        else:
            for notification in plan.notifications:
                send_ntfy(
                    notification.message,
                    notification.title,
                    notification.priority,
                    notification.tags,
                )
            # Commit the transition only after every required notification
            # succeeds. A failed POST therefore retries on the next run.
            atomic_write_json(path, new_state_for(plan))

        print(
            f"Checked {len(plan.components)} components; "
            f"{sum(1 for n in plan.notifications if n.kind == 'down')} down "
            f"transition(s), "
            f"{sum(1 for n in plan.notifications if n.kind == 'up')} recovery."
        )
        return 0
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        RuntimeError,
        TypeError,
    ) as error:
        print(f"Status check failed: {error}", file=sys.stderr)
        return 1


def status_command(*, as_json: bool = False) -> int:
    """Fetch and report the current status without touching state or ntfy."""
    try:
        summary = fetch_json(config.STATUS_URL)
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
        print(f"Status check failed: {error}", file=sys.stderr)
        return 1

    components = watched_components(summary)
    keyword_incidents, incident_titles = active_keyword_incidents(summary)
    active_ids = {
        incident_id
        for values in keyword_incidents.values()
        for incident_id in values
    }

    if as_json:
        payload = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": components,
            "active_keyword_incidents": {
                service: sorted(ids)
                for service, ids in keyword_incidents.items()
                if ids
            },
            "incident_titles": {
                iid: incident_titles[iid] for iid in sorted(active_ids)
            },
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    for name, status in components.items():
        print(f"{name}: {status.replace('_', ' ')}")
    if not active_ids:
        print("No active keyword incidents.")
    else:
        for incident_id in sorted(active_ids):
            print(f"incident {incident_id}: {incident_titles.get(incident_id, '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-status-notify",
        description=(
            "Watch Anthropic's status page and notify ntfy about transitions "
            "in the configured Claude services."
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Fetch and print the current status of watched services, then exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="With --status, emit machine-readable JSON instead of text.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute transitions but do not send notifications or write state; "
            "print what a real run would do."
        ),
    )
    parser.add_argument(
        "--state",
        metavar="PATH",
        help="Override the state file path (default: $STATE_PATH or state.json).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args(argv)

    if args.status:
        return status_command(as_json=args.json)
    # --json is meaningless without --status; a real run always writes text.
    return run(dry_run=args.dry_run, state_path=args.state)


if __name__ == "__main__":
    raise SystemExit(main())