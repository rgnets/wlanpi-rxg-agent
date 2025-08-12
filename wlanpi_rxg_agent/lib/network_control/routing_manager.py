import asyncio
import logging
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Dict, List, Optional, Set

from pyroute2 import NDB, AsyncIPRoute, NetlinkError

from .domain import InterfaceInfo


class RoutingManager:
    """Manages routing tables and IP rules for network interfaces using AsyncIPRoute"""

    def __init__(self, base_table_id: int = 1000):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.base_table_id = base_table_id
        self.interface_tables: Dict[str, int] = {}
        self.configured_interfaces: Set[str] = set()
        self.main_table_routes: Dict[str, List[dict]] = {}
        self.lock = asyncio.Lock()
        self.socket_lock = asyncio.Lock()
        self._startup_complete = False

    async def startup_cleanup(self, interface_names: Set[str]):
        """Clean up any existing routes for our interfaces on startup"""
        async with self.lock:
            if self._startup_complete:
                return

            try:
                self.logger.info(
                    "Performing startup route cleanup for managed interfaces"
                )

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
        self.logger.debug(f"Removing routing for {interface_name}")
        async with self.lock:
            self.logger.debug(f"Lock obtained")
            try:
                table_id = self.interface_tables.get(interface_name)
                if not table_id:
                    self.logger.debug(f"No table ID found for {interface_name}")
                    return True
                self.logger.debug(f"Found {table_id} for {interface_name}")
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
            async with self.socket_lock:
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
                            self.logger.debug(
                                f"Successfully removed rule for table {table_id}"
                            )

                        except Exception as e:
                            # Try alternative approach: delete by table and priority only
                            try:
                                if "FRA_PRIORITY" in attrs:
                                    alt_args = {
                                        "table": table_id,
                                        "priority": attrs["FRA_PRIORITY"],
                                    }
                                    self.logger.debug(
                                        f"Retry with priority-only rule deletion: {alt_args}"
                                    )
                                    await ipr.rule("del", **alt_args)
                                    self.logger.debug(
                                        f"Successfully removed rule with priority-only approach"
                                    )
                                else:
                                    self.logger.warning(
                                        f"Could not delete rule for table {table_id}: {e}"
                                    )
                            except Exception as e2:
                                self.logger.warning(
                                    f"Failed to delete rule for table {table_id}: {e} (retry also failed: {e2})"
                                )

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
                            proto = route.get("proto")

                            delete_args = {"table": table_id}
                            if dst != "default":
                                delete_args["dst"] = dst
                            else:
                                delete_args["dst"] = "default"
                            if gateway:
                                delete_args["gateway"] = gateway
                            if oif:
                                delete_args["oif"] = oif
                            if proto:
                                delete_args["proto"] = proto

                            # Add prefix length for non-default routes
                            if "dst" in delete_args and delete_args["dst"] != "default":
                                if route.get("prefixlen"):
                                    prefixlen = route.get("prefixlen")
                                elif route.get("dst_len"):
                                    prefixlen = route.get("dst_len")
                                else:
                                    prefixlen = 32  # Default to /32 for host routes
                                delete_args["dst"] = f"{delete_args['dst']}/{prefixlen}"

                            await ipr.route("del", **delete_args)
                            self.logger.debug(
                                f"Removed route for table {table_id}: {delete_args}"
                            )

                        except Exception as e:
                            self.logger.debug(f"Error deleting route: {e}")

            self.logger.info(
                f"Flushed routing table {table_id} (removed both rules and routes)"
            )
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

            # Get main_metric early so we don't create a lock conflict.
            main_metric = await self._get_main_table_metric()
            main_table_routes_to_add = []
            async with self.socket_lock:
                async with AsyncIPRoute() as ipr:
                    # 1. Add route to local subnet in the custom table
                    network = interface.ip_address.network
                    await ipr.route(
                        "add", dst=str(network), oif=interface.index, table=table_id
                    )

                    # 2. Add default route via gateway if provided
                    if gateway:
                        self.logger.info(
                            f"Adding default route for {interface.name}: gateway={gateway}, table={table_id}"
                        )
                        await ipr.route(
                            "add",
                            dst="default",
                            gateway=str(gateway),
                            oif=interface.index,
                            table=table_id,
                        )
                        self.logger.debug(
                            f"Default route added successfully for {interface.name}"
                        )

                        main_table_routes_to_add.append([gateway, interface, main_metric])

                    else:
                        self.logger.warning(
                            f"No gateway provided for {interface.name}, skipping default route"
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

            # Use NDB to add routes outside the scope of the IPRoute object to avoid socket conflicts.

            # 2a. Also add gateway to main table with lower metric for poorly designed programs
            for main_table_route in main_table_routes_to_add:
                try:
                    gateway, interface, main_metric = main_table_route

                    self.logger.debug(
                        f"Attempting to add main table route: dst: default, gateway:{str(gateway)}, metric: {main_metric}, oif: {interface.index}, table: {254} "
                    )

                    # Use NDB for main table default route since AsyncIPRoute has issues with multiple default routes
                    await self._add_main_table_default_route_cli(
                        gateway, interface, main_metric
                    )

                    # Track this route for cleanup
                    if interface.name not in self.main_table_routes:
                        self.main_table_routes[interface.name] = []

                    main_route_info = {
                        "dst": "default",
                        "gateway": str(gateway),
                        "oif": interface.index,
                        "metric": main_metric,
                    }
                    self.main_table_routes[interface.name].append(main_route_info)

                    self.logger.info(
                        f"Added gateway {gateway} to main table for {interface.name} with metric {main_metric}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to add gateway to main table for {interface.name}: {e}"
                    )
                    # Continue setup even if main table route fails


            self.logger.debug(
                f"Configured routing for {interface.name}: table={table_id}, "
                f"network={network}, gateway={gateway}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Error setting up routing for {interface.name}: {e}", exc_info=True
            )
            return False

    async def _cleanup_table_and_rules(
        self, interface_name: str, table_id: int
    ) -> bool:
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
        # https://man7.org/linux/man-pages/man7/rtnetlink.7.html
        try:

            async with self.socket_lock:
                async with AsyncIPRoute() as ipr:
                    # Get all rules and find ones in our table range
                    rules_to_delete = []
                    async for rule in await ipr.rule("dump"):
                        rule_table = rule.get("table", 0)
                        if self.base_table_id <= rule_table < self.base_table_id + 1000:
                            rules_to_delete.append((rule_table, rule))

                    self.logger.info(
                        f"Found {len(rules_to_delete)} rules in managed table range"
                    )

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
                            self.logger.debug(
                                f"Successfully removed rule for table {table_id}"
                            )

                        except Exception as e:
                            # Try alternative approach: delete by table and priority only
                            try:
                                if "FRA_PRIORITY" in attrs:
                                    alt_args = {
                                        "table": table_id,
                                        "priority": attrs["FRA_PRIORITY"],
                                    }
                                    self.logger.debug(
                                        f"Retry with priority-only rule deletion: {alt_args}"
                                    )
                                    await ipr.rule("del", **alt_args)
                                    self.logger.debug(
                                        f"Successfully removed rule with priority-only approach for table {table_id}"
                                    )
                                else:
                                    self.logger.warning(
                                        f"Could not delete rule for table {table_id}: {e}"
                                    )
                            except Exception as e2:
                                self.logger.warning(
                                    f"Failed to delete rule for table {table_id}: {e} (retry also failed: {e2})"
                                )

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

                                        if (
                                            "dst" in delete_args
                                            and delete_args["dst"] != "default"
                                        ):
                                            if route.get("prefixlen"):
                                                prefixlen = route.get("prefixlen")
                                            elif route.get("dst_len"):
                                                prefixlen = route.get("dst_len")
                                            else:
                                                prefixlen = (
                                                    32  # Default to /32 for host routes
                                                )
                                            delete_args["dst"] = (
                                                f"{delete_args['dst']}/{prefixlen}"
                                            )
                                        await ipr.route("del", **delete_args)

                                    except Exception as e:
                                        self.logger.error(
                                            f"Error deleting route in table {table_id}: {e}"
                                        )
                        except Exception:
                            # Table doesn't exist or no routes, skip
                            pass

                    if tables_with_routes:
                        self.logger.info(
                            f"Cleaned routes from {len(tables_with_routes)} tables"
                        )

            return True

        except Exception as e:
            self.logger.error(f"Error during cleanup of managed tables: {e}")
            return False

    async def _remove_main_table_routes(self, interface_name: str) -> bool:
        """Remove main table routes for an interface

        NOTE: This only removes default gateway routes and host routes we explicitly added.
        We do NOT remove subnet routes (e.g., 192.168.6.0/24 dev wlan1 proto kernel)
        as those are managed by system hooks and kernel protocols.
        If we later decide to take full control, we would need to modify this.
        """
        try:
            routes_to_remove = self.main_table_routes.get(interface_name, [])
            if not routes_to_remove:
                return True

            async with self.socket_lock:
                async with AsyncIPRoute() as ipr:
                    for route_info in routes_to_remove:
                        try:
                            # Only remove routes we explicitly added (default gateways and host routes)
                            # Skip subnet routes which are managed by kernel/system hooks
                            dst = route_info.get("dst", "")
                            if not (dst == "default" or dst.endswith("/32")):
                                self.logger.debug(
                                    f"Skipping subnet route for {interface_name}: {route_info}"
                                )
                                continue

                            # Remove the main table route (gateway or host route)
                            delete_args = {
                                "table": 254,  # Main table
                                "dst": route_info["dst"],
                                "oif": route_info["oif"],
                            }

                            # Add gateway if specified (for default routes)
                            if "gateway" in route_info:
                                delete_args["gateway"] = route_info["gateway"]

                            # Add metric if it was specified
                            if "metric" in route_info:
                                delete_args["metric"] = route_info["metric"]

                            await ipr.route("del", **delete_args)
                            self.logger.debug(
                                f"Removed main table route for {interface_name}: {delete_args}"
                            )
                        except NetlinkError as e:
                            # Route might not exist, which is fine for removal
                            if "No such file or directory" in str(
                                e
                            ) or "No such process" in str(e):
                                self.logger.debug(
                                    f"Main table route for {interface_name} was already removed"
                                )
                            else:
                                self.logger.warning(
                                    f"Error removing main table route for {interface_name}: {e}"
                                )
                        except Exception as e:
                            self.logger.warning(
                                f"Error removing main table route for {interface_name}: {e}"
                            )

            # Clear tracking for this interface
            self.main_table_routes.pop(interface_name, None)
            self.logger.info(f"Cleaned up main table routes for {interface_name}")
            return True

        except Exception as e:
            self.logger.error(
                f"Error cleaning up main table routes for {interface_name}: {e}"
            )
            return False

    async def _remove_interface_routing(
        self, interface_name: str, table_id: int
    ) -> bool:
        """Remove routing rules and routes for an interface"""
        # First clean up main table routes (only gateways and host routes we added)
        await self._remove_main_table_routes(interface_name)

        # Then clean up dedicated table
        return await self._cleanup_table_and_rules(interface_name, table_id)

    async def cleanup(self):
        """Clean up all configured routing on shutdown"""

        try:
            self.logger.info("Starting routing cleanup for shutdown")

            # Clean up all interfaces we've configured
            self.logger.debug(
                f"Cleaning up all configured interfaces: {self.configured_interfaces}"
            )
            for interface_name in list(self.configured_interfaces):
                self.logger.debug(f"Removing routing for interface: {interface_name}")
                await self.remove_interface_routing(interface_name)
            self.logger.debug("Finished cleaning up all interfaces")

            self.logger.info(
                f"Starting routing cleanup for managed tables: {self.interface_tables}"
            )
            # Additional cleanup: ensure all our table range is clean
            for interface_name, table_id in list(self.interface_tables.items()):
                self.logger.debug(
                    f"Cleaning up table {table_id} for interface {interface_name}"
                )
                await self._cleanup_table_and_rules(interface_name, table_id)
            self.logger.debug(f"Finished cleaning up all tables: ")

            # Clean up any remaining main table routes
            self.logger.debug(
                f"Cleaning up all main table routes: {self.main_table_routes}"
            )
            for interface_name in list(self.main_table_routes.keys()):
                self.logger.debug(
                    f"Cleaning up main table routes for {interface_name}: {self.main_table_routes[interface_name]}"
                )
                await self._remove_main_table_routes(interface_name)
            self.logger.debug("Finished cleaning up all main table routes")

            # Clear our tracking data
            self.configured_interfaces.clear()
            self.interface_tables.clear()
            self.main_table_routes.clear()

            self.logger.info("Routing cleanup completed")

        except Exception as e:
            self.logger.error(f"Error during routing cleanup: {e}")

    async def resolve_host_via_interface(
        self, host: str, interface_name: str
    ) -> Optional[str]:
        """Resolve FQDN to IP address using a specific interface"""
        import ipaddress
        import socket

        # Check if it's already an IP address
        try:
            ipaddress.IPv4Address(host)
            return host  # Already an IP address
        except ipaddress.AddressValueError:
            pass

        try:
            # For now, use system resolver
            # TODO: In the future, could bind to specific interface using dig
            # TODO: This could be a source of bugs potentially, if the host has two IPs each accessible on different interfaces.
            ip = socket.gethostbyname(host)
            self.logger.debug(f"Resolved {host} to {ip}")
            return ip
        except socket.gaierror as e:
            self.logger.error(f"Failed to resolve {host}: {e}")
            return None

    async def _add_main_table_default_route_ndb(
        self, gateway: IPv4Address, interface: InterfaceInfo, metric: int
    ):
        """Add a default route to main table using NDB (works around AsyncIPRoute limitations)"""
        import concurrent.futures

        try:
            async with self.socket_lock:
                with NDB() as ndb:
                    main_route = ndb.routes.create(
                        dst="default",
                        gateway=str(gateway),
                        oif=interface.index,
                        table=254,  # Main table
                        priority=metric,
                    )
                    main_route.commit()
                    return True
        except Exception as e:
            self.logger.error(f"NDB route addition failed: {e}")
            # return False
            raise

    async def _add_main_table_default_route_cli(
        self, gateway: IPv4Address, interface: InterfaceInfo, metric: int
    ):
        """Add a default route to main table using ip command (alternative to NDB)"""
        import asyncio

        try:
            # Build ip route add command
            cmd = [
                "ip",
                "route",
                "add",
                "default",
                "via",
                str(gateway),
                "dev",
                interface.name,
                "metric",
                str(metric),
                "table",
                "254",  # Main table
            ]

            self.logger.debug(f"Running command: {' '.join(cmd)}")

            # Run the command asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                self.logger.debug(
                    f"Successfully added main table default route via CLI: {gateway} dev {interface.name} metric {metric}"
                )
                return True
            else:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                
                # Check if route already exists (not an error for our purposes)
                if "File exists" in error_msg:
                    self.logger.debug(
                        f"Main table route already exists (ignoring): {gateway} dev {interface.name}"
                    )
                    return True
                
                self.logger.error(
                    f"CLI route addition failed (exit code {process.returncode}): {error_msg}"
                )
                raise Exception(f"ip route command failed: {error_msg}")

        except Exception as e:
            self.logger.error(f"CLI route addition failed: {e}")
            raise

    async def _get_main_table_metric(self) -> int:
        """Get an appropriate metric for main table routes (lower priority than existing)"""
        try:
            min_metric = 1024  # Default high metric

            async with self.socket_lock:
                async with AsyncIPRoute() as ipr:
                    # Check existing default routes in main table (254)
                    async for route in await ipr.route("dump", table=254):
                        attrs = dict(route.get("attrs", []))
                        dst = attrs.get("RTA_DST", "default")
                        if dst == "default" or not dst:  # Default route
                            metric = attrs.get("RTA_PRIORITY", 0)
                            if metric and metric < min_metric:
                                min_metric = metric

                    # Return a metric that's 100 higher than the lowest existing metric
                    # This ensures our routes have lower priority
                    return min_metric + 100

        except Exception as e:
            self.logger.warning(f"Error determining main table metric: {e}")
            return 1200  # Safe fallback value

    async def add_host_route(
        self,
        host_ip: str,
        interface_name: str,
        table_id: Optional[int] = None,
        src_ip: Optional[str] = None,
    ) -> bool:
        """Add a /32 route to a specific host via an interface"""
        async with self.lock:
            try:
                # Allow an override for special potatoes.
                if not table_id:
                    # Get the interface's table ID
                    table_id = self.interface_tables.get(interface_name)
                if not table_id:
                    self.logger.error(
                        f"No table ID found for interface {interface_name}"
                    )
                    return False

                # Get interface index and IP if src_ip not provided
                interface_index = None
                interface_ip = None

                async with self.socket_lock:
                    async with AsyncIPRoute() as ipr:
                        # Find interface index and get IP address if needed
                        async for link in await ipr.link("dump"):
                            attrs = dict(link.get("attrs", []))
                            if attrs.get("IFLA_IFNAME") == interface_name:
                                interface_index = link["index"]
                                break

                        # Get interface IP address if src_ip not provided
                        if src_ip is None:
                            async for addr in await ipr.addr("dump", index=interface_index):
                                attrs = dict(addr.get("attrs", []))
                                if "IFA_ADDRESS" in attrs:
                                    interface_ip = attrs["IFA_ADDRESS"]
                                    break

                if interface_index is None:
                    self.logger.error(f"Interface {interface_name} not found")
                    return False

                # Use provided src_ip or detected interface IP
                source_ip = src_ip or interface_ip

                # Get gateway from DHCP lease information for this interface
                gateway_ip = None
                try:
                    from .dhcp_lease_parser import DHCPLeaseParser

                    lease_parser = DHCPLeaseParser(interface_name)
                    lease = lease_parser.latest_lease()

                    if lease and "routers" in lease.options:
                        # Extract the first router from the DHCP lease
                        routers_data = lease.options["routers"].data
                        gateway_ip = routers_data.split()[0]  # Take first router IP
                        self.logger.debug(
                            f"Found gateway {gateway_ip} for {interface_name} from DHCP lease"
                        )
                    else:
                        self.logger.debug(
                            f"No DHCP lease or routers option found for {interface_name}"
                        )

                except Exception as e:
                    self.logger.debug(
                        f"Could not get gateway from DHCP lease for {interface_name}: {e}"
                    )

                # Fallback: Get gateway from the interface's routing table if DHCP failed
                if not gateway_ip:
                    async with self.socket_lock:
                        async with AsyncIPRoute() as ipr:
                            # Look for default route in the interface's table to get gateway
                            async for route in await ipr.route("dump", table=table_id):
                                attrs = dict(route.get("attrs", []))
                                dst = attrs.get("RTA_DST", "default")
                                if dst == "default" or not dst:  # Default route
                                    gateway_ip = attrs.get("RTA_GATEWAY")
                                    if gateway_ip:
                                        self.logger.debug(
                                            f"Found gateway {gateway_ip} for {interface_name} in table {table_id} (fallback)"
                                        )
                                        break

                # Add host route (/32) to the interface's routing table
                route_args = {
                    "dst": f"{host_ip}/32",
                    "oif": interface_index,
                    "table": table_id,
                }

                # Add source IP if specified or detected
                if source_ip:
                    route_args["src"] = source_ip

                # Add gateway if found
                if gateway_ip:
                    route_args["gateway"] = gateway_ip
                    self.logger.debug(
                        f"Using gateway {gateway_ip} for host route to {host_ip}"
                    )
                async with self.socket_lock:
                    async with AsyncIPRoute() as ipr:
                        await ipr.route("add", **route_args)

                src_info = f" src={source_ip}" if source_ip else ""
                gateway_info = f" gateway={gateway_ip}" if gateway_ip else ""
                self.logger.debug(
                    f"Added host route: {host_ip}/32 via {interface_name} (table {table_id}){src_info}{gateway_info}"
                )
                return True

            except Exception as e:
                self.logger.error(
                    f"Error adding host route for {host_ip} via {interface_name}: {e}"
                )
                return False

    async def remove_host_route(
        self, host_ip: str, interface_name: str, table_id: Optional[int] = None
    ) -> bool:
        """Remove a /32 route to a specific host from an interface"""
        async with self.lock:
            try:
                # Allow an override for special potatoes.
                if not table_id:
                    # Get the interface's table ID
                    table_id = self.interface_tables.get(interface_name)
                if not table_id:
                    self.logger.warning(
                        f"No table ID found for interface {interface_name}"
                    )
                    return True  # Consider it success if no table exists

                # Get interface index
                interface_index = None

                async with self.socket_lock:
                    async with AsyncIPRoute() as ipr:
                        # Find interface index
                        async for link in await ipr.link("dump"):
                            attrs = dict(link.get("attrs", []))
                            if attrs.get("IFLA_IFNAME") == interface_name:
                                interface_index = link["index"]
                                break

                if interface_index is None:
                    self.logger.warning(f"Interface {interface_name} not found")
                    return True  # Consider it success if interface doesn't exist

                # Remove host route (/32) from the interface's routing table

                async with self.socket_lock:
                    async with AsyncIPRoute() as ipr:
                        await ipr.route(
                            "del", dst=f"{host_ip}/32", oif=interface_index, table=table_id
                        )

                self.logger.debug(
                    f"Removed host route: {host_ip}/32 via {interface_name} (table {table_id})"
                )
                return True

            except NetlinkError as e:
                # Route might not exist, which is fine for removal
                if "No such file or directory" in str(e) or "No such process" in str(e):
                    self.logger.debug(
                        f"Host route {host_ip}/32 via {interface_name} was already removed"
                    )
                    return True
                else:
                    self.logger.error(
                        f"NetlinkError removing host route for {host_ip} via {interface_name}: {e}"
                    )
                    return False
            except Exception as e:
                self.logger.error(
                    f"Error removing host route for {host_ip} via {interface_name}: {e}"
                )
                return False
