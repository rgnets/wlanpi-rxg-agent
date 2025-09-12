RobotFramework Listener Patterns for rXg Integration

This guide shows two recommended ways to emit structured results from your RobotFramework suites so the agent can collect and return them to the rXg.

The agent automatically parses Robot’s output.xml for lines beginning with the prefix:

- RXG_RESULT: <payload>

If the payload is valid JSON, it is parsed into an object; otherwise, it is included as a raw string. These items are included in the MQTT summary under `result.rxg_results`.

The agent also detects a default listener and passes it to Robot automatically if present in the bundle:

- `<suite_root>/rxg_listener.py` -> `--listener rxg_listener.RxgListener`
- `<suite_root>/robot_libs/rxg_listener.py` -> `--listener robot_libs.rxg_listener.RxgListener`

The suite directory is added to `PYTHONPATH` so these modules can be imported.

1) Keyword-based helper (simple, explicit)

- Create a Python library in your bundle (e.g., `robot_libs/rxg_helpers.py`) with a keyword to log RXG_RESULT lines.

Example `robot_libs/rxg_helpers.py`:

    from robot.libraries.BuiltIn import BuiltIn
    import json

    def report_rxg_result(metric: str, value, **extra):
        payload = {"metric": metric, "value": value}
        if extra:
            payload.update(extra)
        BuiltIn().log(f"RXG_RESULT: {json.dumps(payload)}", level="INFO")

Example use in `.robot`:

    *** Settings ***
    Library    robot_libs/rxg_helpers.py

    *** Test Cases ***
    Report Portal Timing
        ${ms}=    Set Variable    1234
        Report Rxg Result    login_time_ms    ${ms}    portal=${PORTAL_NAME}

2) ListenerV3 (automatic aggregation)

- Provide a listener class to aggregate and emit results without modifying every test.
- If you name it `rxg_listener.py` and place it in one of the known locations, the agent’s runner auto-enables it.

Example `rxg_listener.py`:

    import json

    class RxgListener:
        ROBOT_LISTENER_API_VERSION = 3

        def end_test(self, data, result):
            item = {
                "metric": "test_duration_ms",
                "value": int(result.elapsedtime),
                "test": result.name,
                "status": result.status,
            }
            print(f"RXG_RESULT: {json.dumps(item)}")

        # Optionally implement start_suite/end_suite for aggregated metrics.

Notes
- You can use both approaches together: use keywords for specific values and the listener for consistent run metadata.
- The agent already includes environment variables as Robot variables: `host_name`, `eth0_mac`, `eth0_ip`, `test_interface`, `test_interface_mac`, `test_interface_ip`.

