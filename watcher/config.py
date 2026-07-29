"""Runtime configuration for the Claude status watcher."""

import os

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
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
