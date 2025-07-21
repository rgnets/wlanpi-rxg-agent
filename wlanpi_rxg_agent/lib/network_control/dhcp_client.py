import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .dhcp_lease_parser import DHCPLeaseParser
from .domain import InterfaceInfo


class DHCPClient:
    """Handles DHCP client operations for network interfaces"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.active_clients: dict[str, subprocess.Popen] = {}
        self.lease_parsers: dict[str, DHCPLeaseParser] = {}

    async def start_dhcp_client(self, interface_name: str, timeout: int = 30) -> bool:
        """Start DHCP client for an interface"""
        try:
            # Stop any existing client for this interface
            await self.stop_dhcp_client(interface_name)

            # Start dhclient
            cmd = [
                "dhclient",
                "-v",  # verbose
                "-1",  # try once
                # "-timeout",  # WLAN Pi doesn't have a version that supports the timeout argument.
                # str(timeout),
                interface_name,
            ]

            self.logger.info(f"Starting DHCP client for {interface_name}")
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            # Wait for completion
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                self.logger.info(f"DHCP client successful for {interface_name}")
                # Create lease parser for this interface
                self.lease_parsers[interface_name] = DHCPLeaseParser(interface_name)
                return True
            else:
                self.logger.error(
                    f"DHCP client failed for {interface_name}: {stderr.decode()}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Error starting DHCP client for {interface_name}: {e}")
            return False

    async def stop_dhcp_client(self, interface_name: str) -> bool:
        """Stop DHCP client for an interface"""
        try:
            # Kill any existing dhclient process for this interface
            cmd = ["pkill", "-f", f"dhclient.*{interface_name}"]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            await process.communicate()

            # Remove from tracking
            if interface_name in self.active_clients:
                del self.active_clients[interface_name]

            if interface_name in self.lease_parsers:
                del self.lease_parsers[interface_name]

            self.logger.info(f"Stopped DHCP client for {interface_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error stopping DHCP client for {interface_name}: {e}")
            return False

    async def release_lease(self, interface_name: str) -> bool:
        """Release DHCP lease for an interface"""
        try:
            cmd = ["dhclient", "-r", interface_name]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                self.logger.info(f"Released DHCP lease for {interface_name}")
                return True
            else:
                self.logger.warning(
                    f"Failed to release DHCP lease for {interface_name}: {stderr.decode()}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Error releasing DHCP lease for {interface_name}: {e}")
            return False

    async def renew_lease(self, interface_name: str) -> bool:
        """Renew DHCP lease for an interface"""
        try:
            # First try to renew existing lease
            cmd = ["dhclient", "-n", interface_name]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                self.logger.info(f"Renewed DHCP lease for {interface_name}")
                return True
            else:
                # If renewal fails, try to get a new lease
                self.logger.info(
                    f"Renewal failed, attempting new lease for {interface_name}"
                )
                return await self.start_dhcp_client(interface_name)

        except Exception as e:
            self.logger.error(f"Error renewing DHCP lease for {interface_name}: {e}")
            return False

    def get_lease_info(self, interface_name: str) -> Optional[dict]:
        """Get current lease information for an interface"""
        try:
            parser = self.lease_parsers.get(interface_name)
            if not parser:
                parser = DHCPLeaseParser(interface_name)
                self.lease_parsers[interface_name] = parser

            lease = parser.latest_lease()
            if lease:
                return {
                    "interface": lease.interface,
                    "ip_address": lease.fixed_address,
                    "gateway": (
                        lease.options.get("routers", {}).data
                        if lease.options.get("routers")
                        else None
                    ),
                    "dns_servers": (
                        lease.options.get("domain_name_servers", {}).data
                        if lease.options.get("domain_name_servers")
                        else None
                    ),
                    "subnet_mask": (
                        lease.options.get("subnet_mask", {}).data
                        if lease.options.get("subnet_mask")
                        else None
                    ),
                    "lease_time": (
                        lease.options.get("dhcp_lease_time", {}).data
                        if lease.options.get("dhcp_lease_time")
                        else None
                    ),
                    "expires": lease.expire.value if lease.expire else None,
                }
            return None

        except Exception as e:
            self.logger.error(f"Error getting lease info for {interface_name}: {e}")
            return None

    async def cleanup(self):
        """Clean up all DHCP clients"""
        for interface_name in list(self.active_clients.keys()):
            await self.stop_dhcp_client(interface_name)

        self.logger.info("DHCP client cleanup completed")
