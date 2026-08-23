"""Runtime configuration for the Claude status watcher."""

import os


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on bad input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


STATUS_URL = os.getenv(
    "CLAUDE_STATUS_URL",
    "https://status.anthropic.com/api/v2/summary.json",
)

# Component names must match Anthropic's public status page.
WATCH_COMPONENTS = ("claude.ai", "Claude Code")

# Claude Design is not exposed as a standalone status-page component, so it is
# detected in incident titles and updates instead.
KEYWORD_SERVICES = {
    "Claude Design": ("claude design", "design"),
}

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
STATE_PATH = os.getenv("STATE_PATH", "state.json")

# A non-numeric or non-positive timeout must not crash the whole watcher: fall
# back to a sane default so a typo in an env file can't disable monitoring.
HTTP_TIMEOUT_SECONDS = _env_float("HTTP_TIMEOUT_SECONDS", 20)