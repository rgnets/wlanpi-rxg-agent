import asyncio
import logging
from typing import Dict, Optional, Set
from pyroute2 import AsyncIPRoute, NetlinkError
from ipaddress import IPv4Interface, IPv4Address, IPv4Network
from .domain import InterfaceInfo


class RoutingManager:
    """Manages routing tables and IP rules for network interfaces using AsyncIPRoute"""

    def __init__(self, base_table_id: int = 1000):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.base_table_id = base_table_id
        self.interface_tables: Dict[str, int] = {}
        self.configured_interfaces: Set[str] = set()
        self.lock = asyncio.Lock()

    async def configure_interface_routing(
        self, interface: InterfaceInfo, gateway: Optional[IPv4Address] = None
    ) -> bool:
        """Configure routing for an interface with source-based routing"""
        async with self.lock:
            try:
                if not interface.ip_address:
                    self.logger.warning(f"No IP address for interface {interface.name}")
                    return False

                # Assign a table ID for this interface
                table_id = self._get_table_id(interface.name)

                # Remove existing configuration if any
                await self._remove_interface_routing(interface.name, table_id)

                # Configure routing
                success = await self._setup_interface_routing(
                    interface, table_id, gateway
                )

                if success:
                    self.configured_interfaces.add(interface.name)
                    self.logger.info(
                        f"Successfully configured routing for {interface.name}"
                    )
                else:
                    self.logger.error(
                        f"Failed to configure routing for {interface.name}"
                    )

                return success

            except Exception as e:
                self.logger.error(
                    f"Error configuring routing for {interface.name}: {e}"
                )
                return False

    async def remove_interface_routing(self, interface_name: str) -> bool:
        """Remove routing configuration for an interface"""
        async with self.lock:
            try:
                table_id = self.interface_tables.get(interface_name)
                if not table_id:
                    self.logger.debug(f"No table ID found for {interface_name}")
                    return True

                success = await self._remove_interface_routing(interface_name, table_id)

                if success:
                    self.configured_interfaces.discard(interface_name)
                    self.logger.info(
                        f"Successfully removed routing for {interface_name}"
                    )
                else:
                    self.logger.error(f"Failed to remove routing for {interface_name}")

                return success

            except Exception as e:
                self.logger.error(f"Error removing routing for {interface_name}: {e}")
                return False

    async def flush_table(self, table_id: int) -> bool:
        """Flush all routes from a routing table"""
        try:
            async with AsyncIPRoute() as ipr:
                # Get all routes in the table
                routes = []
                async for route in await ipr.route("dump", table=table_id):
                    routes.append(route)

                # Delete each route
                for route in routes:
                    try:
                        attrs = dict(route.get("attrs", []))
                        dst = attrs.get("RTA_DST", "default")
                        gateway = attrs.get("RTA_GATEWAY")
                        oif = attrs.get("RTA_OIF")

                        delete_args = {"table": table_id}
                        if dst != "default":
                            delete_args["dst"] = dst
                        else:
                            delete_args["dst"] = "default"
                        if gateway:
                            delete_args["gateway"] = gateway
                        if oif:
                            delete_args["oif"] = oif

                        await ipr.route("del", **delete_args)

                    except Exception as e:
                        self.logger.debug(f"Error deleting route: {e}")

            self.logger.info(f"Flushed routing table {table_id}")
            return True

        except Exception as e:
            self.logger.error(f"Error flushing table {table_id}: {e}")
            return False

    async def get_interface_status(self, interface_name: Optional[str] = None) -> Dict:
        """Get routing status for interfaces"""
        try:
            if interface_name:
                table_id = self.interface_tables.get(interface_name)
                configured = interface_name in self.configured_interfaces
                return {
                    "interface": interface_name,
                    "table_id": table_id,
                    "configured": configured,
                }
            else:
                return {
                    "interfaces": dict(self.interface_tables),
                    "configured": list(self.configured_interfaces),
                }
        except Exception as e:
            self.logger.error(f"Error getting interface status: {e}")
            return {}

    def _get_table_id(self, interface_name: str) -> int:
        """Get or assign a table ID for an interface"""
        if interface_name not in self.interface_tables:
            # Use a hash of the interface name to get a consistent table ID
            table_id = self.base_table_id + (hash(interface_name) % 1000)
            self.interface_tables[interface_name] = table_id

        return self.interface_tables[interface_name]

    async def _setup_interface_routing(
        self, interface: InterfaceInfo, table_id: int, gateway: Optional[IPv4Address]
    ) -> bool:
        """Set up routing rules and routes for an interface"""
        try:
            async with AsyncIPRoute() as ipr:
                # 1. Add route to local subnet in the custom table
                network = interface.ip_address.network
                await ipr.route(
                    "add", dst=str(network), oif=interface.index, table=table_id
                )

                # 2. Add default route via gateway if provided
                if gateway:
                    await ipr.route(
                        "add",
                        dst="default",
                        gateway=str(gateway),
                        oif=interface.index,
                        table=table_id,
                    )

                # 3. Add IP rule for source-based routing
                # Traffic from this interface's IP should use this table
                await ipr.rule(
                    "add",
                    src=str(interface.ip_address.ip),
                    table=table_id,
                    priority=table_id,
                )

                # 4. Add IP rule for packets going out this interface
                # This ensures packets destined for this interface's network use this table
                await ipr.rule(
                    "add", dst=str(network), table=table_id, priority=table_id + 1
                )

            self.logger.debug(
                f"Configured routing for {interface.name}: table={table_id}, "
                f"network={network}, gateway={gateway}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error setting up routing for {interface.name}: {e}", exc_info=True)
            return False

    async def _remove_interface_routing(
        self, interface_name: str, table_id: int
    ) -> bool:
        """Remove routing rules and routes for an interface"""
        try:
            async with AsyncIPRoute() as ipr:
                # Remove all rules associated with this table
                rules = []
                async for rule in await ipr.rule("dump"):
                    rule_table = rule.get("table", 0)
                    if rule_table == table_id:
                        rules.append(rule)

                for rule in rules:
                    try:
                        attrs = dict(rule.get("attrs", []))
                        rule_args = {"table": table_id}

                        if "FRA_SRC" in attrs:
                            rule_args["src"] = attrs["FRA_SRC"]
                        if "FRA_DST" in attrs:
                            rule_args["dst"] = attrs["FRA_DST"]
                        if "FRA_PRIORITY" in attrs:
                            rule_args["priority"] = attrs["FRA_PRIORITY"]

                        await ipr.rule("del", **rule_args)

                    except Exception as e:
                        self.logger.debug(f"Error removing rule: {e}")

                # Flush the routing table
                await self.flush_table(table_id)

            self.logger.debug(
                f"Removed routing for {interface_name} (table {table_id})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error removing routing for {interface_name}: {e}")
            return False

    async def cleanup(self):
        """Clean up all configured routing"""
        async with self.lock:
            for interface_name in list(self.configured_interfaces):
                await self.remove_interface_routing(interface_name)
