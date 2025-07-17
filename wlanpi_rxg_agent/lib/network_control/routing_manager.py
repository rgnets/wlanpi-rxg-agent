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
        self._startup_complete = False

    async def startup_cleanup(self, interface_names: Set[str]):
        """Clean up any existing routes for our interfaces on startup"""
        async with self.lock:
            if self._startup_complete:
                return
                
            try:
                self.logger.info("Performing startup route cleanup for managed interfaces")
                
                # Clean up all rules in our table range (base_table_id to base_table_id + 1000)
                await self._cleanup_all_managed_tables()
                
                # Also clean up specific interfaces we'll manage
                for interface_name in interface_names:
                    table_id = self._get_table_id(interface_name)
                    await self._cleanup_table_and_rules(interface_name, table_id)
                    
                self._startup_complete = True
                self.logger.info("Startup route cleanup completed")
                
            except Exception as e:
                self.logger.error(f"Error during startup cleanup: {e}")

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
        """Flush all routes and rules from a routing table"""
        try:
            async with AsyncIPRoute() as ipr:
                # First, remove all IP rules for this table
                rules = []
                async for rule in await ipr.rule("dump"):
                    rule_table = rule.get("table", 0)
                    if rule_table == table_id:
                        rules.append(rule)

                self.logger.debug(f"Found {len(rules)} rules for table {table_id}")

                for rule in rules:
                    try:
                        attrs = dict(rule.get("attrs", []))
                        rule_args = {"table": table_id}

                        # Handle all possible rule attributes
                        if "FRA_SRC" in attrs:
                            rule_args["src"] = attrs["FRA_SRC"]
                        if "FRA_DST" in attrs:
                            rule_args["dst"] = attrs["FRA_DST"]
                        if "FRA_PRIORITY" in attrs:
                            rule_args["priority"] = attrs["FRA_PRIORITY"]
                        if "FRA_FWMARK" in attrs:
                            rule_args["fwmark"] = attrs["FRA_FWMARK"]
                        if "FRA_FWMASK" in attrs:
                            rule_args["fwmask"] = attrs["FRA_FWMASK"]
                        if "FRA_IIFNAME" in attrs:
                            rule_args["iif"] = attrs["FRA_IIFNAME"]
                        if "FRA_OIFNAME" in attrs:
                            rule_args["oif"] = attrs["FRA_OIFNAME"]

                        # Log what we're trying to delete
                        self.logger.debug(f"Attempting to remove rule: {rule_args}")
                        await ipr.rule("del", **rule_args)
                        self.logger.debug(f"Successfully removed rule for table {table_id}")

                    except Exception as e:
                        # Try alternative approach: delete by table and priority only
                        try:
                            if "FRA_PRIORITY" in attrs:
                                alt_args = {"table": table_id, "priority": attrs["FRA_PRIORITY"]}
                                self.logger.debug(f"Retry with priority-only rule deletion: {alt_args}")
                                await ipr.rule("del", **alt_args)
                                self.logger.debug(f"Successfully removed rule with priority-only approach")
                            else:
                                self.logger.warning(f"Could not delete rule for table {table_id}: {e}")
                        except Exception as e2:
                            self.logger.warning(f"Failed to delete rule for table {table_id}: {e} (retry also failed: {e2})")

                # Then, get all routes in the table
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
                        self.logger.debug(f"Removed route for table {table_id}: {delete_args}")

                    except Exception as e:
                        self.logger.debug(f"Error deleting route: {e}")

            self.logger.info(f"Flushed routing table {table_id} (removed both rules and routes)")
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
                    self.logger.info(f"Adding default route for {interface.name}: gateway={gateway}, table={table_id}")
                    await ipr.route(
                        "add",
                        dst="default",
                        gateway=str(gateway),
                        oif=interface.index,
                        table=table_id,
                    )
                    self.logger.debug(f"Default route added successfully for {interface.name}")
                else:
                    self.logger.warning(f"No gateway provided for {interface.name}, skipping default route")

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

    async def _cleanup_table_and_rules(self, interface_name: str, table_id: int) -> bool:
        """Clean up both rules and routes for a table (used by startup and shutdown cleanup)"""
        try:
            # Use flush_table which now handles both rules and routes
            success = await self.flush_table(table_id)
            
            if success:
                self.logger.debug(
                    f"Cleaned up table and rules for {interface_name} (table {table_id})"
                )
            
            return success

        except Exception as e:
            self.logger.error(f"Error cleaning up table for {interface_name}: {e}")
            return False

    async def _cleanup_all_managed_tables(self) -> bool:
        """Clean up all rules and routes in our managed table range"""
        try:
            async with AsyncIPRoute() as ipr:
                # Get all rules and find ones in our table range
                rules_to_delete = []
                async for rule in await ipr.rule("dump"):
                    rule_table = rule.get("table", 0)
                    if self.base_table_id <= rule_table < self.base_table_id + 1000:
                        rules_to_delete.append((rule_table, rule))
                
                self.logger.info(f"Found {len(rules_to_delete)} rules in managed table range")
                
                # Delete rules first
                for table_id, rule in rules_to_delete:
                    try:
                        attrs = dict(rule.get("attrs", []))
                        rule_args = {"table": table_id}

                        # Handle all possible rule attributes for proper identification
                        if "FRA_SRC" in attrs:
                            rule_args["src"] = attrs["FRA_SRC"]
                        if "FRA_DST" in attrs:
                            rule_args["dst"] = attrs["FRA_DST"]
                        if "FRA_PRIORITY" in attrs:
                            rule_args["priority"] = attrs["FRA_PRIORITY"]
                        if "FRA_FWMARK" in attrs:
                            rule_args["fwmark"] = attrs["FRA_FWMARK"]
                        if "FRA_FWMASK" in attrs:
                            rule_args["fwmask"] = attrs["FRA_FWMASK"]
                        if "FRA_IIFNAME" in attrs:
                            rule_args["iif"] = attrs["FRA_IIFNAME"]
                        if "FRA_OIFNAME" in attrs:
                            rule_args["oif"] = attrs["FRA_OIFNAME"]

                        # Log what we're trying to delete for debugging
                        self.logger.debug(f"Attempting to remove rule: {rule_args}")
                        await ipr.rule("del", **rule_args)
                        self.logger.debug(f"Successfully removed rule for table {table_id}")
                        
                    except Exception as e:
                        # Try alternative approach: delete by table and priority only
                        try:
                            if "FRA_PRIORITY" in attrs:
                                alt_args = {"table": table_id, "priority": attrs["FRA_PRIORITY"]}
                                self.logger.debug(f"Retry with priority-only rule deletion: {alt_args}")
                                await ipr.rule("del", **alt_args)
                                self.logger.debug(f"Successfully removed rule with priority-only approach for table {table_id}")
                            else:
                                self.logger.warning(f"Could not delete rule for table {table_id}: {e}")
                        except Exception as e2:
                            self.logger.warning(f"Failed to delete rule for table {table_id}: {e} (retry also failed: {e2})")
                
                # Get all tables in our range and clean routes
                tables_with_routes = set()
                for table_id in range(self.base_table_id, self.base_table_id + 1000):
                    try:
                        routes = []
                        async for route in await ipr.route("dump", table=table_id):
                            routes.append(route)
                            
                        if routes:
                            tables_with_routes.add(table_id)
                            # Delete routes in this table
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
                                    self.logger.debug(f"Error deleting route in table {table_id}: {e}")
                    except Exception:
                        # Table doesn't exist or no routes, skip
                        pass
                
                if tables_with_routes:
                    self.logger.info(f"Cleaned routes from {len(tables_with_routes)} tables")
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error during cleanup of managed tables: {e}")
            return False

    async def _remove_interface_routing(
        self, interface_name: str, table_id: int
    ) -> bool:
        """Remove routing rules and routes for an interface"""
        return await self._cleanup_table_and_rules(interface_name, table_id)

    async def cleanup(self):
        """Clean up all configured routing on shutdown"""
        async with self.lock:
            try:
                self.logger.info("Starting routing cleanup for shutdown")
                
                # Clean up all interfaces we've configured
                for interface_name in list(self.configured_interfaces):
                    await self.remove_interface_routing(interface_name)
                
                # Additional cleanup: ensure all our table range is clean
                for interface_name, table_id in list(self.interface_tables.items()):
                    await self._cleanup_table_and_rules(interface_name, table_id)
                    
                # Clear our tracking data
                self.configured_interfaces.clear()
                self.interface_tables.clear()
                
                self.logger.info("Routing cleanup completed")
                
            except Exception as e:
                self.logger.error(f"Error during routing cleanup: {e}")
