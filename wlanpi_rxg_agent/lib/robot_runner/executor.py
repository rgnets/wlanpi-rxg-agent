import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from wlanpi_rxg_agent.lib.agent_actions.domain import Data
from wlanpi_rxg_agent import utils


class RobotExecutor:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.__class__.__name__}")

    async def run(
        self,
        suite: Data.RobotSuite,
        suite_dir: Path,
    ) -> Tuple[Path, Dict]:
        """Runs a RobotFramework suite.

        Returns (run_dir, metadata) where run_dir contains output.xml/log.html/report.html
        and metadata contains started/ended timestamps.
        """
        run_dir = suite_dir / "runs" / datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        run_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        import sys
        cmd: List[str] = [sys.executable, "-m", "robot", "--outputdir", str(run_dir)]

        # Inject variables
        variables = self._build_variables(suite)
        for k, v in variables.items():
            cmd.extend(["--variable", f"{k}:{v}"])

        # Merge any suite-provided variables
        if suite.variables:
            for k, v in suite.variables.items():
                if v is None:
                    continue
                cmd.extend(["--variable", f"{k}:{v}"])

        # Detect default listener if present in bundle
        listener_spec = self._detect_listener(suite_dir)
        if listener_spec:
            cmd.extend(["--listener", listener_spec])

        # Entrypoint handling
        if suite.entrypoint:
            test_path = suite_dir / suite.entrypoint
        else:
            test_path = suite_dir
        cmd.append(str(test_path))

        env = os.environ.copy()
        # Ensure Python can import bundle libs
        env["PYTHONPATH"] = f"{suite_dir}:{env.get('PYTHONPATH','')}" if env.get("PYTHONPATH") else str(suite_dir)

        self.logger.info(f"Executing RobotFramework: {' '.join(cmd)}")
        started_at = datetime.utcnow().isoformat()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(suite_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = suite.timeout or 600
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Robot run timed out after {timeout}s for suite {suite.id}; terminating process"
                )
                proc.terminate()
                return run_dir, {
                    "started_at": started_at,
                    "ended_at": datetime.utcnow().isoformat(),
                    "returncode": None,
                    "timed_out": True,
                    "stdout": "",
                    "stderr": "",
                }

            ended_at = datetime.utcnow().isoformat()
            meta = {
                "started_at": started_at,
                "ended_at": ended_at,
                "returncode": proc.returncode,
                "timed_out": False,
                "stdout": stdout.decode(errors="ignore"),
                "stderr": stderr.decode(errors="ignore"),
            }
            return run_dir, meta
        except Exception:
            self.logger.exception("Exception running RobotFramework")
            ended_at = datetime.utcnow().isoformat()
            return run_dir, {
                "started_at": started_at,
                "ended_at": ended_at,
                "returncode": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "Exception; see logs",
            }

    def _build_variables(self, suite: Data.RobotSuite) -> Dict[str, str]:
        vars: Dict[str, str] = {}
        try:
            vars["host_name"] = utils.get_hostname()
        except Exception:
            vars["host_name"] = "unknown"
        try:
            vars["eth0_mac"] = utils.get_eth0_mac()
        except Exception:
            vars["eth0_mac"] = "unknown"
        try:
            vars["eth0_ip"] = utils.get_interface_ip_addr("eth0")
        except Exception:
            vars["eth0_ip"] = ""

        iface = suite.interface or ""
        vars["test_interface"] = iface
        if iface:
            try:
                macs = utils.get_interface_macs_by_name()
                vars["test_interface_mac"] = macs.get(iface, "unknown")
            except Exception:
                vars["test_interface_mac"] = "unknown"
            try:
                vars["test_interface_ip"] = utils.get_interface_ip_addr(iface)
            except Exception:
                vars["test_interface_ip"] = ""
        else:
            vars["test_interface_mac"] = ""
            vars["test_interface_ip"] = ""
        return vars

    def _detect_listener(self, suite_dir: Path) -> Optional[str]:
        """Detect a default listener in the suite and return import spec if found.

        Supported locations:
        - <suite_root>/rxg_listener.py -> rxg_listener.RxgListener
        - <suite_root>/robot_libs/rxg_listener.py -> robot_libs.rxg_listener.RxgListener
        """
        if (suite_dir / "rxg_listener.py").exists():
            return "rxg_listener.RxgListener"
        if (suite_dir / "robot_libs" / "rxg_listener.py").exists():
            return "robot_libs.rxg_listener.RxgListener"
        return None
