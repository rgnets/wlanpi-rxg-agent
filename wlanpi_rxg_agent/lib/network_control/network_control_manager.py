import asyncio
import logging
from typing import Dict, Optional, Set
from ipaddress import IPv4Address

from wlanpi_rxg_agent.busses import command_bus, message_bus
from wlanpi_rxg_agent.lib.wifi_control import domain as wifi_domain
from .domain import (
    InterfaceInfo,
    InterfaceState,
    InterfaceType,
    Messages,
    Commands,
)
from .netlink_monitor import AsyncNetlinkMonitor
from .routing_manager import RoutingManager
from .dhcp_client import DHCPClient
from .dhcp_lease_parser import DHCPLeaseParser
from pyroute2.netlink.rtnl import RTM_NEWADDR, RTM_DELADDR, RTM_NEWLINK, RTM_DELLINK


class NetworkControlManager:
    """Main network control manager that coordinates interface monitoring,
    routing configuration, and DHCP management"""

    def __init__(self, wireless_interfaces: Optional[Set[str]] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.wireless_interfaces = wireless_interfaces or set()
        self.managed_interfaces: Dict[str, InterfaceInfo] = {}

        # Initialize components
        self.netlink_monitor = AsyncNetlinkMonitor(wireless_interfaces)
        self.routing_manager = RoutingManager()
        self.dhcp_client = DHCPClient()

        # Setup event handlers
        self.netlink_monitor.add_callback(self._handle_netlink_event)
        self._setup_command_handlers()
        self._setup_wifi_event_handlers()

        self.running = False

    def _setup_command_handlers(self):
        """Setup command bus handlers"""
        command_bus.add_handler(
            Commands.ConfigureInterface, self._handle_configure_interface
        )
        command_bus.add_handler(Commands.RemoveInterface, self._handle_remove_interface)
        command_bus.add_handler(Commands.FlushRoutes, self._handle_flush_routes)
        command_bus.add_handler(
            Commands.GetInterfaceStatus, self._handle_get_interface_status
        )

    def _setup_wifi_event_handlers(self):
        """Setup WiFi event handlers for connectivity loss detection"""
        # Listen for WPA supplicant disconnection events
        message_bus.add_handler(
            wifi_domain.Messages.Disconnection, self._handle_wifi_disconnection
        )
        
        # Listen for WPA supplicant state changes
        message_bus.add_handler(
            wifi_domain.Messages.WpaSupplicantStateChanged, self._handle_wifi_state_change
        )

    async def start(self):
        """Start the network control manager"""
        if self.running:
            return

        self.running = True

        # Clean up any leftover routes from previous crashes
        await self.routing_manager.startup_cleanup(self.wireless_interfaces)

        # Start netlink monitoring
        await self.netlink_monitor.start()

        # Discover and configure existing interfaces
        await self._discover_interfaces()

        self.logger.info("Network control manager started")

    async def stop(self):
        """Stop the network control manager"""
        if not self.running:
            return

        self.running = False

        # Stop components
        await self.netlink_monitor.stop()
        await self.routing_manager.cleanup()
        await self.dhcp_client.cleanup()

        self.logger.info("Network control manager stopped")

    async def _discover_interfaces(self):
        """Discover existing wireless interfaces and configure them"""
        try:
            # Get current interface information
            for interface_name in self.wireless_interfaces:
                interface_info = await self.netlink_monitor._get_interface_info(
                    interface_name
                )
                if interface_info:
                    self.managed_interfaces[interface_name] = interface_info

                    # If interface is up and has IP, configure routing
                    if (
                        interface_info.state == InterfaceState.UP
                        and interface_info.ip_address
                    ):
                        # Get gateway from DHCP lease
                        gateway = await self._get_gateway_from_lease(interface_name)
                        await self._configure_interface_routing(interface_info, gateway)

        except Exception as e:
            self.logger.error(f"Error discovering interfaces: {e}")

    async def _handle_netlink_event(
        self, event_type: str, msg: dict, interface_info: Optional[InterfaceInfo]
    ):
        """Handle netlink events from the monitor"""
        try:
            if not interface_info:
                return

            interface_name = interface_info.name
            msg_type = msg["header"]["type"]

            # Update our interface tracking
            self.managed_interfaces[interface_name] = interface_info

            if event_type == "link_event":
                await self._handle_link_event(msg_type, interface_info)
            elif event_type == "addr_event":
                await self._handle_addr_event(msg_type, interface_info)
            elif event_type == "route_event":
                # Route events are handled separately
                pass

        except Exception as e:
            self.logger.error(f"Error handling netlink event: {e}")

    async def _handle_wifi_disconnection(self, event: wifi_domain.Messages.Disconnection):
        """Handle WiFi disconnection events from WPA supplicant"""
        try:
            interface_name = event.interface
            
            # Only handle interfaces we're managing
            if interface_name not in self.managed_interfaces:
                return
                
            self.logger.info(f"WiFi disconnection detected on {interface_name}")
            
            # Clean up routing and DHCP for this interface
            await self._cleanup_interface_on_disconnect(interface_name)
            
        except Exception as e:
            self.logger.error(f"Error handling WiFi disconnection: {e}")

    async def _handle_wifi_state_change(self, event: wifi_domain.Messages.WpaSupplicantStateChanged):
        """Handle WiFi state changes from WPA supplicant"""
        try:
            interface_name = event.interface
            state = event.state
            
            # Only handle interfaces we're managing
            if interface_name not in self.managed_interfaces:
                return
                
            self.logger.debug(f"WiFi state change on {interface_name}: {state}")
            
            # Handle disconnected/inactive states
            if state.lower() in ["disconnected", "inactive", "interface_disabled"]:
                self.logger.info(f"WiFi connection lost on {interface_name} (state: {state})")
                await self._cleanup_interface_on_disconnect(interface_name)
            elif state.lower() == "completed":
                self.logger.info(f"WiFi connection established on {interface_name}")
                # Note: We don't need to do anything here since netlink events will handle
                # IP address assignment and routing configuration
                
        except Exception as e:
            self.logger.error(f"Error handling WiFi state change: {e}")

    async def _cleanup_interface_on_disconnect(self, interface_name: str):
        """Clean up interface routing and DHCP on WiFi disconnect"""
        try:
            self.logger.info(f"Cleaning up {interface_name} after WiFi disconnect")
            
            # Remove routing configuration
            await self.routing_manager.remove_interface_routing(interface_name)
            
            # Stop DHCP client
            await self.dhcp_client.stop_dhcp_client(interface_name)
            
            # Update interface info to reflect disconnected state
            if interface_name in self.managed_interfaces:
                interface_info = self.managed_interfaces[interface_name]
                interface_info.ip_address = None
                interface_info.gateway = None
                interface_info.has_dhcp_lease = False
                
                # Send connectivity lost event
                message_bus.handle(Messages.ConnectivityLost(interface=interface_info))
                
        except Exception as e:
            self.logger.error(f"Error cleaning up interface {interface_name}: {e}")

    async def _handle_link_event(self, msg_type: int, interface_info: InterfaceInfo):
        """Handle interface link up/down events"""
        try:
            if msg_type == RTM_NEWLINK:
                if interface_info.state == InterfaceState.UP:
                    self.logger.info(f"Interface {interface_info.name} is up")

                    # Trigger DHCP if interface doesn't have IP
                    if not interface_info.ip_address:
                        await self._trigger_dhcp(interface_info.name)

                    # Send interface up event
                    message_bus.handle(Messages.InterfaceUp(interface=interface_info))

            elif msg_type == RTM_DELLINK:
                if interface_info.state == InterfaceState.DOWN:
                    self.logger.info(f"Interface {interface_info.name} is down")

                    # Remove routing configuration
                    await self.routing_manager.remove_interface_routing(
                        interface_info.name
                    )

                    # Stop DHCP client
                    await self.dhcp_client.stop_dhcp_client(interface_info.name)

                    # Send interface down event
                    message_bus.handle(Messages.InterfaceDown(interface=interface_info))

        except Exception as e:
            self.logger.error(
                f"Error handling link event for {interface_info.name}: {e}"
            )

    async def _handle_addr_event(self, msg_type: int, interface_info: InterfaceInfo):
        """Handle IP address assignment/removal events"""
        try:
            if msg_type == RTM_NEWADDR:
                if interface_info.ip_address:
                    self.logger.info(
                        f"IP assigned to {interface_info.name}: {interface_info.ip_address}"
                    )

                    # Get gateway from DHCP lease
                    gateway = await self._get_gateway_from_lease(interface_info.name)

                    # Configure routing
                    await self._configure_interface_routing(interface_info, gateway)

                    # Send address assigned event
                    message_bus.handle(
                        Messages.InterfaceAddressAssigned(interface=interface_info)
                    )

            elif msg_type == RTM_DELADDR:
                self.logger.info(f"IP removed from {interface_info.name}")

                # Remove routing configuration
                await self.routing_manager.remove_interface_routing(interface_info.name)

                # Send address removed event
                message_bus.handle(
                    Messages.InterfaceAddressRemoved(interface=interface_info)
                )

        except Exception as e:
            self.logger.error(
                f"Error handling addr event for {interface_info.name}: {e}"
            )

    async def _trigger_dhcp(self, interface_name: str):
        """Trigger DHCP client for an interface"""
        try:
            self.logger.info(f"Triggering DHCP for {interface_name}")

            success = await self.dhcp_client.start_dhcp_client(interface_name)
            if success:
                # Get lease information
                lease_info = self.dhcp_client.get_lease_info(interface_name)
                if lease_info:
                    # Update interface info with lease data
                    interface_info = self.managed_interfaces.get(interface_name)
                    if interface_info:
                        interface_info.has_dhcp_lease = True

                    # Send DHCP lease acquired event
                    message_bus.handle(
                        Messages.DHCPLeaseAcquired(interface=interface_info)
                    )

        except Exception as e:
            self.logger.error(f"Error triggering DHCP for {interface_name}: {e}")
            message_bus.handle(
                Messages.NetworkControlError(
                    interface_name=interface_name,
                    error_message=f"DHCP trigger failed: {e}",
                    exception=e,
                )
            )

    async def _get_gateway_from_lease(
        self, interface_name: str
    ) -> Optional[IPv4Address]:
        """Get gateway from DHCP lease information"""
        try:
            lease_info = self.dhcp_client.get_lease_info(interface_name)
            if lease_info and lease_info.get("gateway"):
                return IPv4Address(lease_info["gateway"])
            return None

        except Exception as e:
            self.logger.error(
                f"Error getting gateway from lease for {interface_name}: {e}"
            )
            return None

    async def _configure_interface_routing(
        self, interface_info: InterfaceInfo, gateway: Optional[IPv4Address] = None
    ):
        """Configure routing for an interface"""
        try:
            success = await self.routing_manager.configure_interface_routing(
                interface_info, gateway
            )
            if success:
                # Update interface info
                interface_info.gateway = gateway

                # Send route configured event
                message_bus.handle(Messages.RouteConfigured(interface=interface_info))

        except Exception as e:
            self.logger.error(
                f"Error configuring routing for {interface_info.name}: {e}"
            )
            message_bus.handle(
                Messages.NetworkControlError(
                    interface_name=interface_info.name,
                    error_message=f"Routing configuration failed: {e}",
                    exception=e,
                )
            )

    # Command handlers
    async def _handle_configure_interface(self, command: Commands.ConfigureInterface):
        """Handle configure interface command"""
        try:
            interface_name = command.interface_name

            # Get current interface info
            interface_info = await self.netlink_monitor._get_interface_info(
                interface_name
            )
            if not interface_info:
                raise Exception(f"Interface {interface_name} not found")

            # Add to managed interfaces
            self.managed_interfaces[interface_name] = interface_info

            # Force DHCP if requested or if no IP
            if command.force_dhcp or not interface_info.ip_address:
                await self._trigger_dhcp(interface_name)
            else:
                # Configure routing with existing IP
                gateway = await self._get_gateway_from_lease(interface_name)
                await self._configure_interface_routing(interface_info, gateway)

        except Exception as e:
            self.logger.error(
                f"Error configuring interface {command.interface_name}: {e}"
            )
            message_bus.handle(
                Messages.NetworkControlError(
                    interface_name=command.interface_name,
                    error_message=f"Interface configuration failed: {e}",
                    exception=e,
                )
            )

    async def _handle_remove_interface(self, command: Commands.RemoveInterface):
        """Handle remove interface command"""
        try:
            interface_name = command.interface_name

            # Remove routing
            await self.routing_manager.remove_interface_routing(interface_name)

            # Stop DHCP
            await self.dhcp_client.stop_dhcp_client(interface_name)

            # Remove from managed interfaces
            if interface_name in self.managed_interfaces:
                interface_info = self.managed_interfaces.pop(interface_name)
                message_bus.handle(Messages.RouteRemoved(interface=interface_info))

        except Exception as e:
            self.logger.error(f"Error removing interface {command.interface_name}: {e}")
            message_bus.handle(
                Messages.NetworkControlError(
                    interface_name=command.interface_name,
                    error_message=f"Interface removal failed: {e}",
                    exception=e,
                )
            )

    async def _handle_flush_routes(self, command: Commands.FlushRoutes):
        """Handle flush routes command"""
        try:
            await self.routing_manager.flush_table(command.table_id)

        except Exception as e:
            self.logger.error(
                f"Error flushing routes for table {command.table_id}: {e}"
            )

    async def _handle_get_interface_status(self, command: Commands.GetInterfaceStatus):
        """Handle get interface status command"""
        try:
            routing_status = await self.routing_manager.get_interface_status(
                command.interface_name
            )

            if command.interface_name:
                interface_info = self.managed_interfaces.get(command.interface_name)
                return {
                    "interface_info": interface_info,
                    "routing_status": routing_status,
                    "dhcp_lease": self.dhcp_client.get_lease_info(
                        command.interface_name
                    ),
                }
            else:
                return {
                    "managed_interfaces": self.managed_interfaces,
                    "routing_status": routing_status,
                }

        except Exception as e:
            self.logger.error(f"Error getting interface status: {e}")
            return {}
