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
        *,
        python_executable: Optional[Path] = None,
    ) -> Tuple[Path, Dict]:
        """Runs a RobotFramework suite.

        Returns (run_dir, metadata) where run_dir contains output.xml/log.html/report.html
        and metadata contains started/ended timestamps.
        """
        run_dir = suite_dir / "runs" / datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        run_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        import sys

        python_bin = str(python_executable) if python_executable else sys.executable
        cmd: List[str] = [python_bin, "-m", "robot", "--outputdir", str(run_dir)]

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
        if python_executable:
            venv_bin = python_executable.parent
            env["VIRTUAL_ENV"] = str(venv_bin.parent)
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
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
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                timed_out = False
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Robot run timed out after %ss for suite %s; terminating process",
                    timeout,
                    suite.id,
                )
                proc.terminate()
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=30
                    )
                except Exception:
                    stdout, stderr = b"", b""
                timed_out = True

            ended_at = datetime.utcnow().isoformat()
            stdout_text = stdout.decode(errors="ignore")
            stderr_text = stderr.decode(errors="ignore")
            stdout_path, stderr_path = self._write_run_logs(
                run_dir, stdout_text, stderr_text
            )
            self.logger.debug(
                "Robot run stdout for suite %s:\n%s", suite.id, stdout_text or "<empty>"
            )
            self.logger.debug(
                "Robot run stderr for suite %s:\n%s", suite.id, stderr_text or "<empty>"
            )
            self._log_run_result(
                suite=suite,
                returncode=proc.returncode,
                timed_out=timed_out,
                stdout=stdout_text,
                stderr=stderr_text,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            meta = {
                "started_at": started_at,
                "ended_at": ended_at,
                "returncode": proc.returncode,
                "timed_out": timed_out,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "stdout_path": str(stdout_path) if stdout_path else None,
                "stderr_path": str(stderr_path) if stderr_path else None,
                "python_executable": python_bin,
            }
            return run_dir, meta
        except Exception as exc:
            self.logger.exception("Exception running RobotFramework")
            ended_at = datetime.utcnow().isoformat()
            return run_dir, {
                "started_at": started_at,
                "ended_at": ended_at,
                "returncode": None,
                "timed_out": False,
                "stdout": "",
                "stderr": f"Exception: {exc}",
                "stdout_path": None,
                "stderr_path": None,
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

    def _write_run_logs(
        self, run_dir: Path, stdout: str, stderr: str
    ) -> tuple[Optional[Path], Optional[Path]]:
        stdout_path = run_dir / "robot_stdout.log"
        stderr_path = run_dir / "robot_stderr.log"

        def write(path: Path, content: str) -> Optional[Path]:
            try:
                path.write_text(content)
                return path
            except Exception:
                self.logger.exception("Failed writing %s", path)
                return None

        return write(stdout_path, stdout), write(stderr_path, stderr)

    def _log_run_result(
        self,
        suite: Data.RobotSuite,
        returncode: Optional[int],
        timed_out: bool,
        stdout: str,
        stderr: str,
        stdout_path: Optional[Path],
        stderr_path: Optional[Path],
    ) -> None:
        summary = {
            "suite_id": suite.id,
            "entrypoint": suite.entrypoint,
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout_path": str(stdout_path) if stdout_path else None,
            "stderr_path": str(stderr_path) if stderr_path else None,
        }
        if timed_out or returncode not in (0, None):
            self.logger.warning(
                "Robot suite execution issue: %s; stderr preview: %s",
                summary,
                self._summarize(stderr),
            )
        else:
            self.logger.info(
                "Robot suite execution complete: %s; stdout preview: %s",
                summary,
                self._summarize(stdout),
            )

    def _summarize(self, text: str, limit: int = 600) -> str:
        trimmed = text.strip()
        if not trimmed:
            return "<empty>"
        if len(trimmed) <= limit:
            return trimmed
        return f"{trimmed[:limit]}... (truncated, {len(trimmed)} chars)"
