import asyncio
import logging
from typing import Callable, Optional, Set
from pyroute2 import AsyncIPRoute, NetlinkError
from pyroute2.netlink.rtnl import (
    RTM_NEWADDR,
    RTM_DELADDR,
    RTM_NEWLINK,
    RTM_DELLINK,
    RTM_NEWROUTE,
    RTM_DELROUTE,
)
from .domain import InterfaceInfo, InterfaceState, InterfaceType
from ipaddress import IPv4Interface, IPv4Address

# Linux kernel interface flag constants
# These are standard kernel constants defined in if.h
IFF_UP = 0x1       # Interface is up
IFF_RUNNING = 0x40  # Interface is running (resources allocated)


class AsyncNetlinkMonitor:
    """Async netlink monitor for network interface changes using AsyncIPRoute"""

    def __init__(self, wireless_interfaces: Optional[Set[str]] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.wireless_interfaces = wireless_interfaces or set()
        self.callbacks: list[Callable] = []
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None

    def add_callback(self, callback: Callable):
        """Add callback for network events"""
        self.callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """Remove callback for network events"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    async def start(self):
        """Start monitoring netlink events"""
        if self.running:
            return

        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("Netlink monitor started")

    async def stop(self):
        """Stop monitoring netlink events"""
        self.running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Netlink monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop using AsyncIPRoute"""
        try:
            async with AsyncIPRoute() as ipr:
                # Bind to netlink groups for monitoring
                await ipr.bind()

                while self.running:
                    try:
                        # Get messages - AsyncIPRoute.get() doesn't support timeout parameter
                        async for msg in ipr.get():
                            await self._process_message(msg)

                    except NetlinkError as e:
                        if "timeout" not in str(e).lower():
                            self.logger.exception(f"Netlink error: {e}")
                    except Exception as e:
                        self.logger.exception(f"Error in monitor loop: {e}")

        except Exception as e:
            self.logger.exception(f"Monitor loop failed: {e}")
        finally:
            self.logger.info("Monitor loop exited")

    async def _process_message(self, msg):
        """Process netlink message"""
        try:
            msg_type = msg["header"]["type"]

            if msg_type in (RTM_NEWLINK, RTM_DELLINK):
                await self._handle_link_event(msg)
            elif msg_type in (RTM_NEWADDR, RTM_DELADDR):
                await self._handle_addr_event(msg)
            elif msg_type in (RTM_NEWROUTE, RTM_DELROUTE):
                await self._handle_route_event(msg)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_link_event(self, msg):
        """Handle link up/down events"""
        try:
            attrs = dict(msg.get("attrs", []))
            ifname = attrs.get("IFLA_IFNAME")

            if not ifname:
                return

            # Skip non-wireless interfaces if we're filtering
            if self.wireless_interfaces and ifname not in self.wireless_interfaces:
                return

            interface_info = await self._get_interface_info(ifname)
            if interface_info:
                for callback in self.callbacks:
                    try:
                        await callback("link_event", msg, interface_info)
                    except Exception as e:
                        self.logger.error(f"Callback error: {e}")

        except Exception as e:
            self.logger.error(f"Error handling link event: {e}")

    async def _handle_addr_event(self, msg):
        """Handle address assignment/removal events"""
        try:
            attrs = dict(msg.get("attrs", []))
            ifindex = msg.get("index")

            if not ifindex:
                return

            # Get interface name from index
            async with AsyncIPRoute() as ipr:
                try:
                    links = []
                    async for link in await ipr.link("dump", index=ifindex):
                        links.append(link)

                    if not links:
                        return

                    link_attrs = dict(links[0].get("attrs", []))
                    ifname = link_attrs.get("IFLA_IFNAME")

                    if not ifname:
                        return

                    # Skip non-wireless interfaces if we're filtering
                    if (
                        self.wireless_interfaces
                        and ifname not in self.wireless_interfaces
                    ):
                        return

                    interface_info = await self._get_interface_info(ifname)
                    if interface_info:
                        for callback in self.callbacks:
                            try:
                                await callback("addr_event", msg, interface_info)
                            except Exception as e:
                                self.logger.error(f"Callback error: {e}")

                except Exception as e:
                    self.logger.error(f"Error getting interface name: {e}")

        except Exception as e:
            self.logger.error(f"Error handling addr event: {e}")

    async def _handle_route_event(self, msg):
        """Handle routing table changes"""
        try:
            for callback in self.callbacks:
                try:
                    await callback("route_event", msg, None)
                except Exception as e:
                    self.logger.error(f"Callback error: {e}")
        except Exception as e:
            self.logger.error(f"Error handling route event: {e}")

    async def _get_interface_info(self, ifname: str) -> Optional[InterfaceInfo]:
        """Get current interface information using AsyncIPRoute"""
        try:
            async with AsyncIPRoute() as ipr:
                # Get link info
                links = []
                async for link in await ipr.link("dump", ifname=ifname):
                    links.append(link)

                if not links:
                    return None

                link_info = links[0]
                attrs = dict(link_info.get("attrs", []))

                # Determine interface type
                interface_type = InterfaceType.OTHER
                if ifname.startswith("wlan"):
                    interface_type = InterfaceType.WIRELESS
                elif ifname.startswith("eth"):
                    interface_type = InterfaceType.ETHERNET
                elif ifname == "lo":
                    interface_type = InterfaceType.LOOPBACK

                # Determine state
                flags = link_info.get("flags", 0)
                state = (
                    InterfaceState.UP
                    if (flags & IFF_UP) and (flags & IFF_RUNNING)
                    else InterfaceState.DOWN
                )

                # Get MAC address
                mac_address = attrs.get("IFLA_ADDRESS")

                # Get IP address
                ip_address = None
                gateway = None

                try:
                    addrs = []
                    async for addr in await ipr.addr("dump", index=link_info["index"]):
                        addrs.append(addr)

                    for addr in addrs:
                        addr_attrs = dict(addr.get("attrs", []))
                        if addr_attrs.get("IFA_ADDRESS"):
                            ip_str = addr_attrs["IFA_ADDRESS"]
                            prefixlen = addr.get("prefixlen", 24)
                            ip_address = IPv4Interface(f"{ip_str}/{prefixlen}")
                            break
                except Exception as e:
                    self.logger.debug(f"Could not get IP for {ifname}: {e}")

                return InterfaceInfo(
                    name=ifname,
                    index=link_info["index"],
                    state=state,
                    interface_type=interface_type,
                    mac_address=mac_address,
                    ip_address=ip_address,
                    gateway=gateway,
                )

        except Exception as e:
            self.logger.error(f"Error getting interface info for {ifname}: {e}")
            return None
