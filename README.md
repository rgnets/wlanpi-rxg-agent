# WLANPi RXG Agent

## Development Endpoints

### Development Shutdown

The application provides a `/dev_shutdown` endpoint for graceful shutdown during development. This endpoint exists because certain IDEs send a SIGKILL signal before the application has time to clean up resources properly.

**Usage:**
```bash
curl -X POST http://localhost:8200/dev_shutdown \
  -H "Content-Type: application/json" \
  -d '{"CONFIRM": 1}'
```

**Response:**
- When `CONFIRM` is set to 1: Sends SIGTERM to the application process for graceful shutdown
- When `CONFIRM` is not 1: Returns message requiring confirmation

This allows proper cleanup of network interfaces, DHCP clients, and other system resources before termination.

## Makefile Shortcuts

- `make run` — Run the agent locally (`python -m wlanpi_rxg_agent`).
- `make preflight` — Auto-format, lint, import-check, and run unit tests (pre-PR check).
- `make test-unit` — Run unit tests only (excludes integration/hardware/slow).
- `make test` — Run default test suite.
- `make test-integration` — Run integration tests (requires device/network privileges).
- `make cov-html` — Generate coverage HTML report.
- `make lint` — Type/lint checks (mypy, black --check, isort --check, flake8).
- `make format` — Auto-format code (autoflake, black, isort).
- `make gen-reqs` — Re-generate `requirements*.txt` from `pyproject.toml`.
- `make sync` — Sync the repo to a remote dev device (defaults to `root@dev-wlanpi3:/tmp/pycharm_project_880`).

Notes
- The sync target uses `scripts/sync-remote.sh`. Override host/path:
  - `make sync REMOTE_HOST=user@host REMOTE_PATH=/path/on/remote`
- For unit tests on a remote device: `PYTHONPATH=. make test-unit` (ensure `pytest`, `pytest-mock`, `pytest-asyncio` are installed in the remote venv).

## Robot Suites

- The agent can pull and run RobotFramework suites delivered by the rXg and publish compact results via MQTT.
- Suites are pulled via HTTP using a bundle URL and SHA256 and scheduled on intervals respecting a `start_date`.
- Results topic: `wlan-pi/<mac>/agent/ingest/robot`.
- See ROBOT_SUITE_DESIGN.md for full details on configuration, scheduling, variables, and RXG endpoints.
- See ROBOT_LISTENER_GUIDE.md for listener patterns and helper keywords.
