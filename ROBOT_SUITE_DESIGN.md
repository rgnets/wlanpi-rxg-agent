# RobotFramework Suites: Design and Integration

This document describes how RobotFramework test suites are delivered to the WLAN Pi agent, scheduled, executed, and how their results are returned to the rXg.

## Goals

- Pull test bundles via HTTP when the rXg signals updated configuration (primarily via `configure/agent`).
- Schedule and run robot suites on a repeating interval starting from a configured start date.
- Return a compact execution summary via MQTT; optionally upload artifacts via HTTP.
- Support shipping `.robot` files and any `.py` libraries; support optional `requirements.txt` for Python deps.
- Keep suite data on device (ephemeral but persistent) until reconfiguration/removal to avoid churn and flash wear.

## High-Level Architecture

- Domain additions under `lib/agent_actions/domain.py`:
  - `Data.RobotSuite`: suite metadata, schedule, delivery info (`bundle_url`, `bundle_sha256`), runtime vars, upload prefs.
  - `Commands.ConfigureRobotSuites`: configure and schedule suites.
  - `Commands.RunRobotSuite`: trigger immediate run of a suite (one-shot).
  - `Messages.RobotSuiteComplete`: compact summary + optional artifact references.

- Robot subsystem `lib/robot_runner/`:
  - `robot_manager.py`: manages on-disk suites under `/var/lib/wlanpi-rxg-agent/robot_suites/<suite_id>/`; pulls bundles via HTTP when SHA256 changes; applies manifests and prunes obsolete files; installs `requirements.txt` if present.
  - `executor.py`: runs `robot` in the suite context with a per-run output directory; injects device variables (hostname, eth0 MAC/IP, selected interface MAC/IP); enforces timeout; returns paths + metadata.
  - `result_parser.py`: parses `output.xml` to create a compact summary and extracts special result lines (prefixed with `RXG_RESULT:`) for structured reporting.

- Scheduler integration (`lib/tasker/tasker.py`):
  - New schedule bucket `robot_suites` managed via a `configure_test`-style handler.
  - `RepeatingTask` created with `interval` and `start_date` for interval-after-start scheduling.
  - Snapshot persistence updated to include `robot_suites`.

- MQTT integration (`rxg_mqtt_client.py`):
  - Accept `configure/agent` payloads containing `robot_suites` and forward to `Commands.ConfigureRobotSuites`.
  - Legacy `configure/robot_suites` endpoint optionally supported.
  - Publish `Messages.RobotSuiteComplete` to `wlan-pi/<mac>/agent/ingest/robot` as JSON.

- Actions runner (`lib/agent_actions/actions.py`):
  - New handler for `Commands.RunRobotSuite` which delegates to the robot subsystem (manager + executor), parses results, and emits `Messages.RobotSuiteComplete`.

## Delivery & Updates

- Primary delivery mode: HTTP pull. Each suite definition includes:
  - `bundle_url`: HTTPS URL on the rXg to download a compressed bundle (zip or tar.gz).
  - `bundle_sha256`: server-provided SHA256 for the bundle content.
  - The device downloads the bundle when the SHA256 has changed or is missing locally.
  - If a `requirements.txt` exists in the bundle root, it is installed with `python -m pip install -r requirements.txt` into the agent venv (best-effort, with timeout + logging). Network is required on the device for this step.

- Bundle format: zip or tar.gz. Bundle should contain:
  - One or more `.robot` files and any supporting `.py` libraries.
  - Optional `requirements.txt` (see above).
  - Optional `manifest.json` (not required; agent will create its own manifest with file checksums and bundle SHA).

## Scheduling

- Scheduling is interval-based, starting at an optional `start_date` (UTC timestamps accepted); subsequent runs repeat every `period` seconds.
- Where applicable, other tests may be updated in future to respect `start_date`, but this change is initially scoped to Robot Suites.

## Result Reporting

- MQTT Summary (default):
  - Topic: `wlan-pi/<mac>/agent/ingest/robot`
  - Payload: `Messages.RobotSuiteComplete` containing suite id, started/ended timestamps, totals (passed/failed/skipped), per-suite summaries, duration, and extracted `RXG_RESULT:` items.

- HTTP Artifact Upload (optional, future):
  - New rXg endpoint (to be implemented): `Api::RobotResultsController#submit_results`.
  - POST multipart with zip of `output.xml`, `report.html`, `log.html`, and possibly extra artifacts.
  - The agent will include upload status/IDs in the MQTT summary when enabled in the suite config (e.g., `upload_method=http`).

## Variables Injection

Injected into robot runs as variables (names are stable and lower_snake_case):

- `host_name`: hostname of the device
- `eth0_mac`, `eth0_ip`
- `test_interface`: interface name specified by the suite definition
- `test_interface_mac`, `test_interface_ip` (when resolvable)

These are appended to any variables provided in the suite config.

## Persistence & Retention

- Suite data and per-run output directories are kept until the suite is reconfigured or removed. This avoids unnecessary unpacking/rewriting and flash wear.
- `lib/tasker/store.py` snapshot gains a `robot_suites` entry and is used to restore schedules on startup.

## Security Considerations

- Robot bundles may include arbitrary Python code. We assume the rXg is a trusted source.
- Robot runs execute as the agent user, with `PYTHONPATH` restricted to the suite directory.
- Requirements installation is optional, only when a `requirements.txt` is included. Failures are logged and do not crash the agent.

## RXG-side Controllers (to be implemented)

References in local dev tree:
- Subscriber: `~/Repos/rxg/rxgd/bin/mqtt_subscriber_wlanpi`
- AP Registration: `~/Repos/rxg/console/app/controllers/api/apcert_controller.rb`
- TCPDumps (form upload reference): `~/Repos/rxg/console/app/controllers/api/tcpdumps_controller.rb`

Proposed new RXG models/controllers:
- `RobotSuite` (model) and `RobotSuiteResults` (model)
- `Api::RobotSuitesController`
  - `#bundle`: serve the bundle file for a suite as zip/tar.gz with `Content-SHA256` header; authorize per-device.
- `Api::RobotResultsController`
  - `#submit_results`: accept multipart zip upload from device (token- or mTLS-protected), associate with suite + device record, and return a result ID.

Agent references to align with RXG endpoints:
- `Data.RobotSuite.bundle_url` should be the URL to `Api::RobotSuitesController#bundle`.
- `Messages.RobotSuiteComplete` back to MQTT includes `suite_id` and optional `upload_result_id` returned by `#submit_results` (when used).

## Implementation Steps (Agent)

1. Domain updates: add RobotSuite data/commands/messages; extend `ConfigureAgent` to include `robot_suites`.
2. Robot subsystem: manager (download/apply), executor (run/timeout), parser (output.xml + `RXG_RESULT:` lines).
3. Tasker integration: schedule `robot_suites` with `start_date` respected; snapshot/restore support.
4. MQTT integration: `configure/agent` to feed robot suites config; add legacy `configure/robot_suites`; publish `RobotSuiteComplete` to MQTT.
5. Actions: implement `RunRobotSuite` handler to run-once and emit results.
6. Dependencies: add `robotframework` to requirements.
7. Tests: unit tests for parser and manager manifest logic; smoke path for scheduling.

## Notes

- Future improvement: support cron expressions and more advanced schedules, sandboxing, and bundle signatures.

