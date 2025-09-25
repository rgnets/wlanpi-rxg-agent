import asyncio
import hashlib
import inspect
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wlanpi_rxg_agent.api_client import ApiClient
from wlanpi_rxg_agent.busses import command_bus, message_bus
from wlanpi_rxg_agent.lib.agent_actions.domain import Data
from wlanpi_rxg_agent.lib.rxg_supplicant import domain as supplicant_domain


SUITES_BASE_DIR = Path("/var/lib/wlanpi-rxg-agent/robot_suites")


@dataclass
class SuitePaths:
    suite_dir: Path
    manifest_path: Path


@dataclass
class SuitePreparation:
    suite_dir: Path
    python_executable: Path
    pip_log: str


class RobotManager:
    def __init__(self, api_client: Optional[ApiClient] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.__class__.__name__}")
        self.api_client = api_client
        self._active_server: Optional[str] = None
        message_bus.add_handler(
            supplicant_domain.Messages.NewCertifiedConnection,
            self._handle_new_certified_connection,
        )

    def _paths_for(self, suite_id: int) -> SuitePaths:
        suite_dir = SUITES_BASE_DIR / str(suite_id)
        return SuitePaths(suite_dir=suite_dir, manifest_path=suite_dir / "manifest.json")

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def _read_manifest(self, manifest_path: Path) -> dict:
        try:
            with open(manifest_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_manifest(self, manifest_path: Path, data: dict) -> None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = manifest_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, manifest_path)

    def _sha256(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _extract_bundle(self, content: bytes, dest_dir: Path) -> None:
        # Clear existing content for clean update
        if dest_dir.exists():
            for child in dest_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except Exception:
                        pass
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)

        byts = io.BytesIO(content)
        # First try zip
        try:
            with zipfile.ZipFile(byts) as zf:
                zf.extractall(dest_dir)
                return
        except zipfile.BadZipFile:
            pass

        # Reset buffer for tar
        byts.seek(0)
        try:
            with tarfile.open(fileobj=byts, mode="r:gz") as tf:
                tf.extractall(dest_dir)
                return
        except tarfile.TarError:
            pass

        # Try plain tar (no gzip)
        byts.seek(0)
        try:
            with tarfile.open(fileobj=byts, mode="r:") as tf:
                tf.extractall(dest_dir)
                return
        except tarfile.TarError as e:
            raise RuntimeError("Unsupported bundle format (not zip or tar)") from e

    async def ensure_suite(self, suite: Data.RobotSuite) -> SuitePreparation:
        """Ensure the suite files are current, virtualenv ready, and requirements installed."""
        if suite.id is None:
            raise ValueError("RobotSuite.id is required")
        paths = self._paths_for(suite.id)
        self._ensure_dir(paths.suite_dir)
        manifest = self._read_manifest(paths.manifest_path)
        current_sha = manifest.get("bundle_sha256")
        target_sha = suite.bundle_sha256
        suite_dir_exists = paths.suite_dir.exists()
        need_refresh = not (
            target_sha and current_sha == target_sha and suite_dir_exists
        )

        server_ip = await self._get_active_server()
        api_client = self._ensure_api_client(server_ip)

        refresh_performed = False

        if need_refresh:
            if not suite.bundle_url and not server_ip:
                self.logger.warning(
                    "RobotSuite %s missing bundle_url and active server; using existing files if present.",
                    suite.id,
                )
            else:
                response = await api_client.download_robot_suite_bundle(
                    suite_id=suite.id,
                    bundle_url=suite.bundle_url,
                    ip=server_ip,
                )

                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Failed to fetch RobotSuite bundle for suite {suite.id}: {response.status_code} {response.reason}"
                    )

                bundle_url = suite.bundle_url or response.url
                self.logger.info(
                    "Fetching RobotSuite bundle for id=%s from %s", suite.id, bundle_url
                )
                content = response.content
                if suite.bundle_sha256:
                    calc = self._sha256(content)
                    if calc != suite.bundle_sha256:
                        raise RuntimeError(
                            f"Bundle SHA256 mismatch for suite {suite.id}: expected {suite.bundle_sha256}, got {calc}"
                        )

                self._extract_bundle(content, paths.suite_dir)

                new_manifest = {
                    "bundle_sha256": suite.bundle_sha256,
                    "bundle_url": bundle_url,
                }
                self._write_manifest(paths.manifest_path, new_manifest)
                refresh_performed = True

        python_exe = self._ensure_virtualenv(
            paths.suite_dir, force=refresh_performed
        )
        pip_log = await self._maybe_install_requirements(paths.suite_dir, python_exe)
        return SuitePreparation(paths.suite_dir, python_exe, pip_log)

    async def _handle_new_certified_connection(
        self, event: supplicant_domain.Messages.NewCertifiedConnection
    ) -> None:
        self._active_server = event.host
        if self.api_client:
            self.api_client.ip = event.host

    def _ensure_api_client(self, server_ip: Optional[str]) -> ApiClient:
        if self.api_client is None and server_ip:
            self.api_client = ApiClient(server_ip=server_ip)
        elif self.api_client is None:
            self.api_client = ApiClient()

        if server_ip:
            self.api_client.ip = server_ip
        return self.api_client

    async def _get_active_server(self) -> Optional[str]:
        if self._active_server:
            return self._active_server

        if not command_bus.has_handler_for(supplicant_domain.Commands.GetActiveServer):
            return None

        try:
            server = command_bus.handle(
                supplicant_domain.Commands.GetActiveServer()
            )
            if inspect.isawaitable(server):
                server = await server
        except Exception:
            self.logger.exception("Failed to retrieve active server from supplicant")
            return None

        if server:
            self._active_server = server
        return server

    def _ensure_virtualenv(self, suite_dir: Path, *, force: bool = False) -> Path:
        venv_dir = suite_dir / ".venv"
        python_executable = venv_dir / "bin" / "python"

        if force and venv_dir.exists():
            self.logger.debug("Removing existing virtualenv for suite at %s", venv_dir)
            shutil.rmtree(venv_dir, ignore_errors=True)

        if not python_executable.exists():
            self.logger.debug("Creating virtualenv for suite at %s", venv_dir)
            builder = venv.EnvBuilder(symlinks=True, with_pip=True, clear=False)
            try:
                builder.create(str(venv_dir))
            except Exception:
                self.logger.exception(
                    "venv.EnvBuilder failed; attempting subprocess fallback for suite at %s",
                    venv_dir,
                )
                python_executable = self._create_virtualenv_fallback(venv_dir)
                return python_executable
        else:
            self.logger.debug("Reusing existing virtualenv for suite at %s", venv_dir)

        if not python_executable.exists():
            self.logger.warning(
                "Virtualenv python not found at %s; attempting fallback creation", python_executable
            )
            python_executable = self._create_virtualenv_fallback(venv_dir)

        if not python_executable.exists():
            self.logger.warning(
                "Virtualenv creation failed; falling back to system python %s", sys.executable
            )
            return Path(sys.executable)

        return python_executable

    def _create_virtualenv_fallback(self, venv_dir: Path) -> Path:
        python_executable = venv_dir / "bin" / "python"
        cmd = [sys.executable, "-m", "venv", "--symlinks", str(venv_dir)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.logger.warning(
                "Fallback 'python -m venv' failed (code %s): %s",
                proc.returncode,
                proc.stderr.decode(errors="ignore"),
            )
            return Path(sys.executable)
        return python_executable

    async def _maybe_install_requirements(
        self, suite_dir: Path, python_exe: Path
    ) -> str:
        req_file = suite_dir / "requirements.txt"
        if not req_file.exists():
            self.logger.debug("No requirements.txt found for suite at %s", suite_dir)
            return "requirements.txt not found"
        log = await self._pip_install_requirements(python_exe, req_file)
        self.logger.debug(
            "pip install output for suite at %s:\n%s", suite_dir, log or "<empty>"
        )
        return log

    async def _pip_install_requirements(self, python_exe: Path, req_file: Path) -> str:
        """Install requirements with pip into the provided virtualenv. Returns combined output."""

        self.logger.info("Installing RobotSuite requirements from %s", req_file)
        try:
            proc = await asyncio.create_subprocess_exec(
                str(python_exe),
                "-m",
                "pip",
                "install",
                "-r",
                str(req_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                self.logger.warning(
                    "pip install timed out for RobotSuite requirements.txt"
                )
                proc.terminate()
                return "pip install timed out"
            combined = stdout.decode(errors="ignore") + stderr.decode(errors="ignore")
            if proc.returncode != 0:
                self.logger.warning(
                    "pip install failed (code %s) for %s", proc.returncode, req_file
                )
            else:
                self.logger.info("pip install completed for RobotSuite requirements")
            return combined.strip()
        except Exception:
            self.logger.exception("Exception during pip install of RobotSuite requirements")
            return "pip install raised exception"
