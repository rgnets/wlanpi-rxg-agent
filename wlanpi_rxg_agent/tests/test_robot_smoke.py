import json
from pathlib import Path

import pytest

from wlanpi_rxg_agent.lib.robot_runner.executor import RobotExecutor
from wlanpi_rxg_agent.lib.robot_runner.result_parser import parse_output_xml
from wlanpi_rxg_agent.lib.agent_actions.domain import Data


@pytest.mark.integration
def test_robot_smoke_executes_and_emits_rxg_result(tmp_path: Path):
    try:
        import robot  # noqa: F401
    except Exception:
        pytest.skip("robotframework not installed in test environment")

    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()

    (suite_dir / "smoke.robot").write_text(
        """
*** Settings ***
Library    BuiltIn

*** Test Cases ***
Emit RXG Result
    Log    RXG_RESULT: {"metric": "smoke", "value": 1}
        """.strip(),
        encoding="utf-8",
    )

    suite = Data.RobotSuite(
        id=1,
        name="smoke",
        period=10,
        entrypoint="smoke.robot",
    )

    executor = RobotExecutor()
    import asyncio
    run_dir, meta = asyncio.get_event_loop().run_until_complete(
        executor.run(suite, suite_dir)
    )

    output_xml = Path(run_dir) / "output.xml"
    assert output_xml.exists()
    parsed = parse_output_xml(output_xml)
    assert parsed.total >= 1
    assert parsed.rxg_results is not None
    assert any(item.get("metric") == "smoke" for item in parsed.rxg_results if isinstance(item, dict))
