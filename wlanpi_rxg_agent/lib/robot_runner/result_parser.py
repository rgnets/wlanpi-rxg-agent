import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class RobotParsedSummary:
    total: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: Optional[float]
    rxg_results: Optional[List[Dict]]


def parse_output_xml(path: Path) -> RobotParsedSummary:
    """Parse RobotFramework output.xml into a compact summary.

    Also scans <msg> nodes for special lines with prefix "RXG_RESULT:".
    When present, it attempts to parse the remainder as JSON; if parsing fails,
    the raw string is included.
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        logger.warning(f"Failed to parse output.xml at {path}: {e}")
        return RobotParsedSummary(total=0, passed=0, failed=0, skipped=0, duration_seconds=None, rxg_results=None)

    # Totals: Robot 5 output.xml structure => <statistics> or <suite statistics>
    total = passed = failed = skipped = 0
    duration = None

    # Try status on root suite
    try:
        # status has attributes: status="PASS/FAIL" starttime/endtime; duration derivable
        suite = root.find("suite")
        if suite is not None:
            st = suite.find("status")
            if st is not None:
                # Robot timestamps are like 20250211 12:34:56.789
                start = st.attrib.get("starttime")
                end = st.attrib.get("endtime")
                if start and end:
                    # Avoid heavy parsing; leave to executor metadata usually. Keep None here.
                    pass
    except Exception:
        pass

    # Count tests
    try:
        for tc in root.findall(".//test"):
            total += 1
            st = tc.find("status")
            if st is not None:
                if st.attrib.get("status") == "PASS":
                    passed += 1
                elif st.attrib.get("status") == "FAIL":
                    failed += 1
                else:
                    skipped += 1
    except Exception:
        pass

    # Extract RXG_RESULT lines
    rxg_items: List[Dict] = []
    try:
        for msg in root.findall(".//msg"):
            if msg.text and msg.text.strip().startswith("RXG_RESULT:"):
                payload = msg.text.strip()[len("RXG_RESULT:") :].strip()
                # Try JSON parse
                try:
                    import json

                    rxg_items.append(json.loads(payload))
                except Exception:
                    rxg_items.append({"raw": payload})
    except Exception:
        pass

    return RobotParsedSummary(
        total=total, passed=passed, failed=failed, skipped=skipped, duration_seconds=duration, rxg_results=rxg_items or None
    )

