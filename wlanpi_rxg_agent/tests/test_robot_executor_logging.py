import asyncio
import logging
from pathlib import Path

import pytest

from wlanpi_rxg_agent.lib.agent_actions.domain import Data
from wlanpi_rxg_agent.lib.robot_runner.executor import RobotExecutor


@pytest.mark.integration
def test_robot_executor_captures_output_and_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    try:
        import robot  # noqa: F401
    except Exception:
        pytest.skip("robotframework not installed in test environment")

    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "example.robot").write_text(
        """
*** Settings ***
Library    BuiltIn

*** Test Cases ***
Validate Logging
    Log    Hello from Robot
        """.strip(),
        encoding="utf-8",
    )

    suite = Data.RobotSuite(
        id=42,
        name="log-check",
        period=10,
        entrypoint="example.robot",
    )

    executor = RobotExecutor()
    logger_name = "wlanpi_rxg_agent.lib.robot_runner.executor"
    with caplog.at_level(logging.INFO, logger=logger_name):
        run_dir, meta = asyncio.run(executor.run(suite, suite_dir))

    stdout_path = meta.get("stdout_path")
    stderr_path = meta.get("stderr_path")
    assert stdout_path, "stdout path should be provided in metadata"
    stdout_file = Path(stdout_path)
    assert stdout_file.exists(), "stdout log file should have been created"
    stdout_text = stdout_file.read_text(encoding="utf-8")
    assert "Hello from Robot" in stdout_text

    if stderr_path:
        stderr_file = Path(stderr_path)
        assert stderr_file.exists(), "stderr log file should have been created"

    assert meta["returncode"] == 0
    assert meta["timed_out"] is False
    assert "Hello from Robot" in meta["stdout"]

    assert any(
        "Robot suite execution complete" in record.message
        for record in caplog.records
        if record.name == logger_name
    ), "Executor should log a completion message"

