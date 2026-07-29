# Claude Status Notify

A small, dependency-free watcher that checks Anthropic's public status page and
sends [ntfy](https://ntfy.sh/) notifications when Claude services go down or
recover.

It monitors:

- `claude.ai`
- `Claude Code`
- Claude Design mentions in active incidents

The watcher runs automatically with GitHub Actions. It does not require a local
computer or a dedicated server.

## Subscribe to the alerts

Anyone can receive this watcher's Claude status notifications:

1. Install the [ntfy app](https://ntfy.sh/).
2. Add a subscription using the `https://ntfy.sh` server.
3. Subscribe to the topic `claude-status-noti-tanbaydar`.

Notifications can also be viewed in a browser at
[ntfy.sh/claude-status-noti-tanbaydar](https://ntfy.sh/claude-status-noti-tanbaydar).

## How it works

GitHub Actions runs the watcher about every five minutes. Each run:

1. Fetches Anthropic's current status.
2. Compares it with the previous snapshot in `state.json`.
3. Sends one ntfy alert when a service becomes degraded or unavailable.
4. Sends one recovery message when the service becomes operational again.
5. Saves the new snapshot for the next run.

Unchanged conditions do not produce repeated notifications. The first run only
initializes the snapshot and is intentionally silent.

## Setup

### 1. Subscribe in ntfy

Install the ntfy mobile app and subscribe to the topic you want to use on the
`https://ntfy.sh` server.

Treat the topic name as private: anyone who knows a public ntfy topic may be able
to subscribe or publish to it.

### 2. Add the GitHub secret

In this repository, open:

**Settings → Secrets and variables → Actions → New repository secret**

Create the following secret:

| Name | Value |
| --- | --- |
| `NTFY_TOPIC` | Your ntfy topic name |

The topic stays in GitHub's encrypted secrets and should not be committed to the
repository.

### 3. Allow state updates

Open:

**Settings → Actions → General → Workflow permissions**

Select **Read and write permissions**, then save the setting. The workflow needs
this permission to commit the updated `state.json`.

### 4. Start the watcher

Open:

**Actions → Watch Claude status → Run workflow**

The initial run records the current status without notifying. Subsequent checks
run automatically on the schedule in `.github/workflows/watch.yml`.

GitHub Actions schedules may occasionally be delayed during periods of high
load.

## Notification behavior

- Degraded or unavailable services produce a batched high-priority alert.
- Recoveries produce a batched normal-priority message.
- Missing component data is treated as non-operational.
- State is saved only after notifications succeed, so failed deliveries can be
  retried on the next run.

## Configuration

The workflow only requires `NTFY_TOPIC`. These optional environment variables
are available for alternate deployments and testing:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NTFY_SERVER` | `https://ntfy.sh` | Use a self-hosted ntfy server |
| `STATE_PATH` | `state.json` | Change the state file location |
| `CLAUDE_STATUS_URL` | Anthropic summary API | Use an alternate status endpoint |
| `HTTP_TIMEOUT_SECONDS` | `20` | Set the HTTP timeout |

## Tests

```sh
python3 -m unittest discover -s tests -v
```

No third-party Python packages are required.
