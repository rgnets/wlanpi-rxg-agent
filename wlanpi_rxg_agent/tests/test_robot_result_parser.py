import json
from pathlib import Path

from wlanpi_rxg_agent.lib.robot_runner.result_parser import parse_output_xml


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_parse_output_xml_extracts_totals_and_rxg_results(tmp_path: Path):
    # Minimal Robot output.xml structure with two tests and RXG_RESULT lines
    xml = """
    <robot generated="20250101 00:00:00.000" generator="Robot 6.1">
      <suite name="Root Suite">
        <test name="Test A">
          <kw name="Log">
            <msg level="INFO" timestamp="20250101 00:00:01.000">RXG_RESULT: {\"metric\": \"login_time_ms\", \"value\": 1234}</msg>
          </kw>
          <status status="PASS" starttime="20250101 00:00:00.000" endtime="20250101 00:00:02.000" />
        </test>
        <test name="Test B">
          <kw name="Log">
            <msg level="INFO" timestamp="20250101 00:00:03.000">RXG_RESULT: some-unstructured-text</msg>
          </kw>
          <status status="FAIL" starttime="20250101 00:00:03.000" endtime="20250101 00:00:04.000" />
        </test>
        <status status="FAIL" starttime="20250101 00:00:00.000" endtime="20250101 00:00:05.000" />
      </suite>
    </robot>
    """.strip()
    f = tmp_path / "output.xml"
    _write(f, xml)

    parsed = parse_output_xml(f)

    # Totals: 2 tests, 1 pass, 1 fail
    assert parsed.total == 2
    assert parsed.passed == 1
    assert parsed.failed == 1

    # RXG_RESULT items: one json, one raw
    assert parsed.rxg_results is not None
    assert len(parsed.rxg_results) == 2

    # First item should be parsed JSON
    assert parsed.rxg_results[0]["metric"] == "login_time_ms"
    assert parsed.rxg_results[0]["value"] == 1234

    # Second item should be raw text
    assert parsed.rxg_results[1]["raw"] == "some-unstructured-text"

