# Repository Guidelines

## Project Structure & Module Organization
- Source: `wlanpi_rxg_agent/`; entry: `__main__.py` (Uvicorn serving `rxg_agent.app`).
- Subsystems: `wlanpi_rxg_agent/lib/` (e.g., `network_control/`, `configuration/`).
- Tests: `wlanpi_rxg_agent/tests/` and `wlanpi_rxg_agent/tests/integration/`.
- Tooling: `scripts/`; packaging: `debian/`; containers: `docker/`.

## Build, Test, and Development Commands
- Setup: `pip install -r requirements.txt -r requirements-dev.txt`; build: `python -m build`.
- Run (dev): `python -m wlanpi_rxg_agent` (serves on `0.0.0.0:8200`). Dev shutdown: `curl -X POST http://localhost:8200/dev_shutdown -H 'Content-Type: application/json' -d '{"CONFIRM": 1}'`.
- Daemon mode: `python -m wlanpi_rxg_agent.the_daemon`; alt: `uvicorn wlanpi_rxg_agent.rxg_agent:app --host 0.0.0.0 --port 8200`.
- Lint: `scripts/lint.sh` (mypy, black --check, isort --check, flake8). Format: `scripts/format.sh` (autoflake, black, isort).
- Tests: unit `scripts/test.sh` or `pytest`; integration `scripts/test-integration.sh`; coverage HTML `scripts/test-cov-html.sh`.
 - Unit-only: `scripts/test-unit.sh` (excludes integration/hardware/slow markers).

## Docker & Debian Packaging
- Build tools image: `cd docker/tools && ./build.sh`; run: `docker run -it --rm -v "$PWD":/usr/src/app wlanpi-rxg-agent-tools bash`.
- Debian package (inside Debian/bookworm or the tools image): from repo root run `debuild -us -uc` (outputs `.deb` in parent dir). Uses `dh-virtualenv` to install under `/opt/wlanpi-rxg-agent` and a systemd service `wlanpi-rxg-agent.service`.

## Architecture Overview
- Event-driven core using `MessageBus`/`CommandBus` (`wlanpi_rxg_agent/busses.py`) for loose coupling between components.
- Supplicant (`lib/rxg_supplicant/`): discovers rXg, registers with CSR, retrieves cert/CA, emits `Certified` for downstream consumers.
- Bridge config (`lib/configuration/bridge_config_file.py`): writes `/etc/wlanpi-mqtt-bridge/config.toml`; `RXGAgent` restarts the bridge on new certs.
- MQTT client (`rxg_mqtt_client.py`): restarts/reattaches on `Certified` events; uses `aiomqtt` with resilient reconnects.
- Network control (`lib/network_control/`): manages interfaces, routing tables and DHCP with `pyroute2`.
- Scheduler (`lib/tasker/`): `AsyncIOScheduler` with wrappers for repeating/one-shot tests; configured via bus commands.

## Coding Style & Naming Conventions
- Python 3.9+. 4‑space indentation. Prefer type hints (checked by `mypy`).
- Formatting: `black`; imports: `isort` (profile=black). Lint rules: `flake8` (max line length 88).
- Naming: modules/vars/functions `snake_case`; classes `CamelCase`; constants `UPPER_SNAKE_CASE` (see `constants.py`).

## Testing Guidelines
- Framework: `pytest`; discovery: `test_*.py`, `Test*`, `test_*`.
- Markers: `unit` (default), `integration`, `hardware`, `slow`. Example: `pytest -m "not integration and not hardware"`.
- Place unit tests under `wlanpi_rxg_agent/tests/`; integration under `wlanpi_rxg_agent/tests/integration/`.

## Commit & Pull Request Guidelines
- Commits: concise, imperative subject (≤72 chars). Reference issues/PRs where relevant (e.g., "Fix MQTT reconnect on error (#123)").
- Before opening a PR: run `scripts/format.sh`, `scripts/lint.sh`, and all applicable tests.
- PRs should include: problem statement, summary of changes, test plan (commands/outputs), any screenshots/logs, and linked issues.

## Security & Configuration Tips
- Do not commit secrets. Configuration APIs live under `wlanpi_rxg_agent/lib/configuration/`; default TOML path: `install/etc/wlanpi-rxg-agent/config.toml`.
- The agent and integration tests change network state; use test hardware or containers.

## Observability
- Env vars: `RXG_LOG_LEVEL` (global), `RXG_BUS_LOG` (on/off), `RXG_BUS_LOG_LEVEL`, `RXG_BUS_LOG_PAYLOAD` (on/off).
- Bus logging records received/succeeded/failed messages; enable payloads only when debugging.

### Systemd Drop-in (example)
- Create: `/etc/systemd/system/wlanpi-rxg-agent.service.d/override.conf`
```
[Service]
Environment=RXG_LOG_LEVEL=INFO
Environment=RXG_BUS_LOG=on
Environment=RXG_BUS_LOG_LEVEL=INFO
Environment=RXG_BUS_LOG_PAYLOAD=off
```
- Apply: `sudo systemctl daemon-reload && sudo systemctl restart wlanpi-rxg-agent`
