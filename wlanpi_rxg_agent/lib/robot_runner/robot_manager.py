import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp

from wlanpi_rxg_agent.lib.agent_actions.domain import Data


SUITES_BASE_DIR = Path("/var/lib/wlanpi-rxg-agent/robot_suites")


@dataclass
class SuitePaths:
    suite_dir: Path
    manifest_path: Path


class RobotManager:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.__class__.__name__}")

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

    async def _http_get(self, url: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()

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

    async def ensure_suite(self, suite: Data.RobotSuite) -> Path:
        """Ensure the suite files are present and up to date. Returns suite directory.

        If `bundle_sha256` differs from the manifest, downloads from `bundle_url` and extracts.
        """
        if suite.id is None:
            raise ValueError("RobotSuite.id is required")
        paths = self._paths_for(suite.id)
        self._ensure_dir(paths.suite_dir)
        manifest = self._read_manifest(paths.manifest_path)
        current_sha = manifest.get("bundle_sha256")
        target_sha = suite.bundle_sha256

        if target_sha and current_sha == target_sha and paths.suite_dir.exists():
            # Already up to date
            return paths.suite_dir

        if not suite.bundle_url:
            # No URL provided; keep existing files if any
            self.logger.warning(
                f"RobotSuite {suite.id} missing bundle_url; using existing files if present."
            )
            return paths.suite_dir

        self.logger.info(
            f"Fetching RobotSuite bundle for id={suite.id} from {suite.bundle_url}"
        )
        content = await self._http_get(suite.bundle_url)
        if suite.bundle_sha256:
            calc = self._sha256(content)
            if calc != suite.bundle_sha256:
                raise RuntimeError(
                    f"Bundle SHA256 mismatch for suite {suite.id}: expected {suite.bundle_sha256}, got {calc}"
                )

        self._extract_bundle(content, paths.suite_dir)

        # Auto-install requirements if present
        req = paths.suite_dir / "requirements.txt"
        if req.exists():
            await self._pip_install_requirements(req)

        new_manifest = {
            "bundle_sha256": suite.bundle_sha256,
            "bundle_url": suite.bundle_url,
        }
        self._write_manifest(paths.manifest_path, new_manifest)
        return paths.suite_dir

    async def _pip_install_requirements(self, req_file: Path) -> None:
        """Install requirements with pip into the current environment.

        Best-effort; logs failures but does not raise.
        """
        import sys
        import subprocess

        self.logger.info(f"Installing RobotSuite requirements from {req_file}")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
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
                self.logger.warning("pip install timed out for RobotSuite requirements.txt")
                proc.terminate()
                return
            if proc.returncode != 0:
                self.logger.warning(
                    f"pip install failed (code {proc.returncode}): {stderr.decode(errors='ignore')}"
                )
            else:
                self.logger.info("pip install completed for RobotSuite requirements")
        except Exception:
            self.logger.exception("Exception during pip install of RobotSuite requirements")

