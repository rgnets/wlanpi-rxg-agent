"""
Network Control Module

This module provides async network interface monitoring and management using pyroute2.
It handles:
- Real-time netlink monitoring for interface changes
- Source-based routing configuration for multi-interface setups
- DHCP client management and lease tracking
- Event bus integration for communication with other modules

Main components:
- NetworkControlManager: Main coordinator class
- AsyncNetlinkMonitor: Async netlink event monitoring
- RoutingManager: Routing table and IP rule management
- DHCPClient: DHCP client operations
- DHCPLeaseParser: DHCP lease file parsing

Usage:
    from wlanpi_rxg_agent.lib.network_control import NetworkControlManager

    # Create manager for specific wireless interfaces
    manager = NetworkControlManager(wireless_interfaces={'wlan0', 'wlan1'})

    # Start monitoring
    await manager.start()

    # Stop when done
    await manager.stop()
"""

from .dhcp_client import DHCPClient
from .dhcp_lease_parser import DHCPLeaseParser
from .domain import Commands, InterfaceInfo, InterfaceState, InterfaceType, Messages
from .netlink_monitor import AsyncNetlinkMonitor
from .network_control_manager import NetworkControlManager
from .routing_manager import RoutingManager

__all__ = [
    "NetworkControlManager",
    "AsyncNetlinkMonitor",
    "RoutingManager",
    "DHCPClient",
    "DHCPLeaseParser",
    "InterfaceInfo",
    "InterfaceState",
    "InterfaceType",
    "Messages",
    "Commands",
]
