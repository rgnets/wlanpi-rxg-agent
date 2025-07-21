"""
NDB-based routing manager implementation
This is a rewrite of routing_manager.py using pyroute2's NDB interface instead of AsyncIPRoute
"""

import asyncio
import logging
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Dict, List, Optional, Set

from pyroute2 import NDB

from .domain import InterfaceInfo


class RoutingManager:
    """Manages routing tables and IP rules for network interfaces using NDB (Network Database)"""

    def __init__(self, base_table_id: int = 1000):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing NDB-based routing manager")

        # Configuration
        self.base_table_id = base_table_id

        # State tracking
        self.interface_tables: Dict[str, int] = {}  # interface_name -> table_id
        self.configured_interfaces: Set[str] = set()
        self.main_table_routes: Dict[str, List[Dict]] = {}  # interface -> [route_info]

    async def startup_cleanup(self, managed_interfaces: Set[str]):
        """Clean up any leftover routes/rules from previous runs"""
        self.logger.info("Performing startup route cleanup for managed interfaces")

        with NDB() as ndb:
            # Clean up rules in our table range
            rules_to_remove = []
            for rule in ndb.rules:
                if (
                    hasattr(rule, "table")
                    and self.base_table_id <= rule.table < self.base_table_id + 1000
                ):
                    rules_to_remove.append(rule)

            self.logger.info(
                f"Found {len(rules_to_remove)} rules in managed table range"
            )

            for rule in rules_to_remove:
                try:
                    rule.remove().commit()
                    self.logger.debug(
                        f"Removed rule: table={rule.table}, priority={rule.priority}"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to remove rule: {e}")

            # Clean up routes in our table range
            for table_id in range(self.base_table_id, self.base_table_id + 1000):
                try:
                    self._flush_table_ndb(ndb, table_id)
                except Exception as e:
                    self.logger.debug(f"Table {table_id} cleanup: {e}")

        self.logger.info("Startup route cleanup completed")

    def _flush_table_ndb(self, ndb: NDB, table_id: int):
        """Flush all routes and rules from a routing table using NDB"""
        # Remove all routes from the table
        routes_to_remove = [r for r in ndb.routes if r.table == table_id]
        for route in routes_to_remove:
            try:
                route.remove().commit()
            except Exception as e:
                self.logger.debug(f"Failed to remove route from table {table_id}: {e}")

        # Remove all rules pointing to the table
        rules_to_remove = [r for r in ndb.rules if r.table == table_id]
        for rule in rules_to_remove:
            try:
                rule.remove().commit()
            except Exception as e:
                self.logger.debug(f"Failed to remove rule for table {table_id}: {e}")

        if routes_to_remove or rules_to_remove:
            self.logger.info(
                f"Flushed routing table {table_id} (removed {len(routes_to_remove)} routes and {len(rules_to_remove)} rules)"
            )

    async def configure_interface_routing(
        self, interface: InterfaceInfo, gateway: Optional[IPv4Address] = None
    ) -> bool:
        """Configure routing for an interface using NDB"""
        try:
            table_id = self._get_table_id(interface.name)
            return self._setup_interface_routing_ndb(interface, table_id, gateway)
        except Exception as e:
            self.logger.error(f"Failed to configure routing for {interface.name}: {e}")
            return False

    def _setup_interface_routing_ndb(
        self, interface: InterfaceInfo, table_id: int, gateway: Optional[IPv4Address]
    ) -> bool:
        """Set up routing rules and routes for an interface using NDB"""
        try:
            with NDB() as ndb:
                # 1. Add route to local subnet in the custom table
                network = interface.ip_address.network

                subnet_route = ndb.routes.create(
                    dst=str(network), oif=interface.index, table=table_id
                )
                subnet_route.commit()

                self.logger.debug(
                    f"Added subnet route: {network} via {interface.name} (table {table_id})"
                )

                # 2. Add default route if gateway provided
                if gateway:
                    self.logger.info(
                        f"Adding default route for {interface.name}: gateway={gateway}, table={table_id}"
                    )

                    default_route = ndb.routes.create(
                        dst="default",
                        gateway=str(gateway),
                        oif=interface.index,
                        table=table_id,
                    )
                    default_route.commit()

                    self.logger.debug(
                        f"Default route added successfully for {interface.name}"
                    )

                    # 2a. Also add gateway to main table with lower metric for poorly designed programs
                    try:
                        main_metric = self._get_main_table_metric_ndb(ndb)
                        self.logger.debug(
                            f"Adding main table route: dst=default, gateway={gateway}, metric={main_metric}, oif={interface.index}, table=254"
                        )

                        main_route = ndb.routes.create(
                            dst="default",
                            gateway=str(gateway),
                            oif=interface.index,
                            table=254,  # Main table
                            priority=main_metric,
                        )
                        main_route.commit()

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

                # 3. Add IP rule for source-based routing
                ip_rule = ndb.rules.create(
                    src=str(interface.ip_address.ip), table=table_id, priority=table_id
                )
                ip_rule.commit()

                # 4. Add subnet rule for local network
                subnet_rule = ndb.rules.create(
                    dst=str(network), table=table_id, priority=table_id + 1
                )
                subnet_rule.commit()

                self.configured_interfaces.add(interface.name)
                self.logger.info(
                    f"Successfully configured routing for {interface.name} (table {table_id})"
                )
                return True

        except Exception as e:
            self.logger.error(
                f"Error setting up interface routing for {interface.name}: {e}"
            )
            return False

    def _get_main_table_metric_ndb(self, ndb: NDB) -> int:
        """Get an appropriate metric for main table routes using NDB"""
        try:
            min_metric = 1024  # Default high metric

            # Check existing default routes in main table (254)
            for route in ndb.routes:
                if route.table == 254 and route.dst == "default":
                    metric = getattr(route, "priority", 0) or 0
                    if metric and metric < min_metric:
                        min_metric = metric

            # Return a metric that's 100 higher than the lowest existing metric
            return min_metric + 100

        except Exception as e:
            self.logger.warning(f"Error determining main table metric: {e}")
            return 1200  # Safe fallback value

    def _get_table_id(self, interface_name: str) -> int:
        """Get or assign a routing table ID for an interface"""
        if interface_name not in self.interface_tables:
            # Generate a unique table ID based on interface name hash
            base_hash = hash(interface_name) % 1000
            table_id = self.base_table_id + base_hash
            self.interface_tables[interface_name] = table_id
            self.logger.debug(f"Assigned table ID {table_id} to {interface_name}")
        return self.interface_tables[interface_name]

    async def add_host_route(
        self,
        host_ip: str,
        interface_name: str,
        table_id: Optional[int] = None,
        src_ip: Optional[str] = None,
    ) -> bool:
        """Add a /32 route to a specific host via an interface using NDB"""
        try:
            with NDB() as ndb:
                # Use provided table_id or get interface's dedicated table
                target_table = table_id or self._get_table_id(interface_name)

                # Find interface info
                interface_index = None
                interface_ip = None

                for iface in ndb.interfaces:
                    if iface.ifname == interface_name:
                        interface_index = iface.index
                        break

                if interface_index is None:
                    self.logger.error(f"Interface {interface_name} not found")
                    return False

                # Get interface IP if needed for source IP
                if not src_ip:
                    for addr in ndb.addresses:
                        if (
                            addr.index == interface_index
                            and hasattr(addr, "address")
                            and not str(addr.address).startswith("fe80")
                        ):  # Skip link-local
                            interface_ip = str(addr.address)
                            break

                # Use provided src_ip or detected interface IP
                source_ip = src_ip or interface_ip

                # Create route
                route_args = {
                    "dst": f"{host_ip}/32",
                    "oif": interface_index,
                    "table": target_table,
                }

                # Add source IP if specified or detected
                if source_ip:
                    route_args["src"] = source_ip

                route = ndb.routes.create(**route_args)
                route.commit()

                src_info = f" src={source_ip}" if source_ip else ""
                self.logger.debug(
                    f"Added host route: {host_ip}/32 via {interface_name} (table {target_table}){src_info}"
                )
                return True

        except Exception as e:
            self.logger.error(
                f"Error adding host route for {host_ip} via {interface_name}: {e}"
            )
            return False

    async def remove_host_route(self, host_ip: str, interface_name: str) -> bool:
        """Remove a /32 host route using NDB"""
        try:
            with NDB() as ndb:
                table_id = self._get_table_id(interface_name)

                # Find the route to remove
                route_to_remove = None
                for route in ndb.routes:
                    if route.table == table_id and route.dst == f"{host_ip}/32":
                        route_to_remove = route
                        break

                if route_to_remove:
                    route_to_remove.remove().commit()
                    self.logger.debug(
                        f"Removed host route: {host_ip}/32 from {interface_name}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"Host route {host_ip}/32 not found for {interface_name}"
                    )
                    return False

        except Exception as e:
            self.logger.error(
                f"Error removing host route for {host_ip} via {interface_name}: {e}"
            )
            return False

    async def remove_interface_routing(self, interface_name: str) -> bool:
        """Remove routing configuration for an interface"""
        try:
            with NDB() as ndb:
                table_id = self.interface_tables.get(interface_name)
                if table_id:
                    # Remove all routes and rules for this interface
                    self._flush_table_ndb(ndb, table_id)

                    # Remove main table routes for this interface
                    await self._remove_main_table_routes(interface_name)

                    # Remove from tracking
                    del self.interface_tables[interface_name]
                    self.configured_interfaces.discard(interface_name)
                    self.main_table_routes.pop(interface_name, None)

                    self.logger.info(
                        f"Successfully removed routing for {interface_name}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"No routing configuration found for {interface_name}"
                    )
                    return False
        except Exception as e:
            self.logger.error(f"Error removing routing for {interface_name}: {e}")
            return False

    async def flush_table(self, table_id: int) -> bool:
        """Flush all routes and rules from a specific routing table"""
        try:
            with NDB() as ndb:
                self._flush_table_ndb(ndb, table_id)
                return True
        except Exception as e:
            self.logger.error(f"Error flushing table {table_id}: {e}")
            return False

    async def get_interface_status(self, interface_name: Optional[str] = None) -> Dict:
        """Get status information for interfaces"""
        try:
            with NDB() as ndb:
                if interface_name:
                    # Return status for specific interface
                    table_id = self.interface_tables.get(interface_name)
                    is_configured = interface_name in self.configured_interfaces

                    # Count routes in interface table
                    route_count = 0
                    if table_id:
                        route_count = sum(1 for r in ndb.routes if r.table == table_id)

                    return {
                        interface_name: {
                            "configured": is_configured,
                            "table_id": table_id,
                            "route_count": route_count,
                            "main_table_routes": len(
                                self.main_table_routes.get(interface_name, [])
                            ),
                        }
                    }
                else:
                    # Return status for all interfaces
                    status = {}
                    for iface_name in self.interface_tables.keys():
                        status.update(await self.get_interface_status(iface_name))
                    return status
        except Exception as e:
            self.logger.error(f"Error getting interface status: {e}")
            return {}

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

    async def _remove_main_table_routes(self, interface_name: str) -> bool:
        """Remove main table routes for an interface"""
        try:
            with NDB() as ndb:
                routes_info = self.main_table_routes.get(interface_name, [])

                for route_info in routes_info:
                    try:
                        # Find and remove the route
                        for route in ndb.routes:
                            if (
                                route.table == 254
                                and route.dst == route_info["dst"]
                                and route.gateway == route_info["gateway"]
                                and route.oif == route_info["oif"]
                            ):
                                route.remove().commit()
                                self.logger.debug(
                                    f"Removed main table route: {route_info}"
                                )
                                break
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to remove main table route {route_info}: {e}"
                        )

                # Clear the tracking
                self.main_table_routes.pop(interface_name, None)
                return True
        except Exception as e:
            self.logger.error(
                f"Error removing main table routes for {interface_name}: {e}"
            )
            return False

    async def cleanup(self):
        """Clean up all managed routing tables and rules"""
        self.logger.info("Starting routing cleanup for shutdown")

        try:
            with NDB() as ndb:
                # Clean up all tables we created
                for table_id in self.interface_tables.values():
                    try:
                        self._flush_table_ndb(ndb, table_id)
                    except Exception as e:
                        self.logger.warning(f"Failed to clean up table {table_id}: {e}")
        except Exception as e:
            self.logger.error(f"Error during routing cleanup: {e}")

        # Clear state
        self.interface_tables.clear()
        self.configured_interfaces.clear()
        self.main_table_routes.clear()

        self.logger.info("Routing cleanup completed")
