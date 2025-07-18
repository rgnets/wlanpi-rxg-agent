"""
Enhanced routing integration tests for NetworkControlManager and RoutingManager

These tests verify the new routing enhancements:
- Host route management with optional source IP
- Main table default gateway with lower metric  
- Comprehensive cleanup of main table routes
- Smart metric assignment logic

Tests require:
- Root or CAP_NET_ADMIN permissions
- Actual wireless interfaces
- Ability to manipulate routing tables

Use with caution on production systems.
"""

import asyncio
import logging
import subprocess
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from typing import Dict, List, Optional, Set

import pytest
import pytest_asyncio

from wlanpi_rxg_agent.lib.network_control import NetworkControlManager
from wlanpi_rxg_agent.lib.network_control.domain import (
    Commands,
    HostRouteResult,
    InterfaceInfo,
    InterfaceState,
    InterfaceType,
)
from wlanpi_rxg_agent.lib.network_control.routing_manager import RoutingManager

logger = logging.getLogger(__name__)


def get_available_wireless_interfaces() -> Set[str]:
    """Get actually available wireless interfaces on the system"""
    sys_net = Path("/sys/class/net")
    if not sys_net.exists():
        return set()

    wireless_interfaces = set()
    for interface_path in sys_net.iterdir():
        if interface_path.name.startswith("wlan"):
            # Check if it's actually a wireless interface
            wireless_path = interface_path / "wireless"
            if wireless_path.exists():
                wireless_interfaces.add(interface_path.name)

    return wireless_interfaces


def check_interface_exists(interface_name: str) -> bool:
    """Check if a network interface exists"""
    return Path(f"/sys/class/net/{interface_name}").exists()


def run_command(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run a system command and return result"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {' '.join(cmd)}")
        raise
    except Exception as e:
        logger.error(f"Command failed: {' '.join(cmd)}, error: {e}")
        raise


async def get_interface_ip(interface_name: str) -> Optional[str]:
    """Get the IP address of an interface"""
    try:
        result = run_command(["ip", "-4", "addr", "show", interface_name])
        if result.returncode != 0:
            return None
        
        # Parse IP from output like: inet 192.168.1.100/24
        for line in result.stdout.split('\n'):
            if 'inet ' in line and 'scope global' in line:
                parts = line.strip().split()
                for i, part in enumerate(parts):
                    if part == 'inet' and i + 1 < len(parts):
                        ip_with_mask = parts[i + 1]
                        return ip_with_mask.split('/')[0]
        return None
    except Exception as e:
        logger.error(f"Error getting IP for {interface_name}: {e}")
        return None


async def check_route_exists(dst: str, table: int = 254, src: Optional[str] = None) -> bool:
    """Check if a specific route exists in a routing table"""
    try:
        cmd = ["ip", "route", "show", "table", str(table)]
        if dst != "default":
            cmd.extend(["to", dst])
        
        result = run_command(cmd)
        if result.returncode != 0:
            return False
        
        # Look for the route in the output
        for line in result.stdout.split('\n'):
            if dst in line or (dst == "default" and "default" in line):
                if src is None:
                    return True
                elif f"src {src}" in line:
                    return True
        return False
    except Exception as e:
        logger.error(f"Error checking route {dst} in table {table}: {e}")
        return False


async def get_main_table_default_routes() -> List[Dict]:
    """Get all default routes from main table with their metrics"""
    try:
        result = run_command(["ip", "route", "show", "table", "254"])
        if result.returncode != 0:
            return []
        
        routes = []
        for line in result.stdout.split('\n'):
            if line.strip().startswith('default'):
                # Parse metric if present
                metric = None
                if 'metric' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'metric' and i + 1 < len(parts):
                            metric = int(parts[i + 1])
                            break
                
                routes.append({
                    'line': line.strip(),
                    'metric': metric or 0
                })
        
        return routes
    except Exception as e:
        logger.error(f"Error getting main table routes: {e}")
        return []


@pytest_asyncio.fixture
async def routing_manager():
    """Create a RoutingManager instance for testing"""
    manager = RoutingManager(base_table_id=9000)  # Use high table ID to avoid conflicts
    
    # Clean up any existing test routes
    await manager.startup_cleanup(set())
    
    yield manager
    
    # Clean up after test
    await manager.cleanup()


@pytest.fixture
def available_interfaces():
    """Get available wireless interfaces, skip if none found"""
    interfaces = get_available_wireless_interfaces()
    if not interfaces:
        pytest.skip("No wireless interfaces found for testing")
    return interfaces


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_host_route_with_source_ip(routing_manager, available_interfaces):
    """Test adding host routes with automatic source IP detection"""
    interface_name = next(iter(available_interfaces))
    
    # Get current interface IP
    interface_ip = await get_interface_ip(interface_name)
    if not interface_ip:
        pytest.skip(f"Interface {interface_name} has no IP address")
    
    logger.info(f"Testing host route on {interface_name} with IP {interface_ip}")
    
    # Test host for routing (use a common DNS server)
    test_host = "8.8.8.8"
    
    # Ensure table ID is assigned for the interface
    table_id = routing_manager._get_table_id(interface_name)
    
    # Add host route without specifying source IP (should auto-detect)
    success = await routing_manager.add_host_route(
        host_ip=test_host,
        interface_name=interface_name
    )
    
    assert success, f"Failed to add host route for {test_host}"
    
    # Verify route was added to dedicated table with source IP
    table_id = routing_manager.interface_tables.get(interface_name)
    assert table_id is not None, f"No table ID assigned for {interface_name}"
    
    # Check that route exists (we can't easily verify src in integration test)
    route_exists = await check_route_exists(f"{test_host}/32", table_id)
    assert route_exists, f"Host route {test_host}/32 not found in table {table_id}"
    
    # Test with explicit source IP
    test_host_2 = "8.8.4.4"
    success = await routing_manager.add_host_route(
        host_ip=test_host_2,
        interface_name=interface_name,
        src_ip=interface_ip
    )
    
    assert success, f"Failed to add host route for {test_host_2} with explicit src"
    
    # Clean up
    await routing_manager.remove_host_route(test_host, interface_name)
    await routing_manager.remove_host_route(test_host_2, interface_name)
    
    logger.info("✓ Host route with source IP test passed")


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_main_table_gateway_management(routing_manager, available_interfaces):
    """Test adding gateways to main table with appropriate metrics"""
    interface_name = next(iter(available_interfaces))
    
    # Get current interface IP
    interface_ip = await get_interface_ip(interface_name)
    if not interface_ip:
        pytest.skip(f"Interface {interface_name} has no IP address")
    
    logger.info(f"Testing main table gateway on {interface_name}")
    
    # Get current main table default routes before test
    initial_routes = await get_main_table_default_routes()
    initial_count = len(initial_routes)
    logger.info(f"Initial main table default routes: {initial_count}")
    
    # Create a mock interface info for testing
    interface_info = InterfaceInfo(
        name=interface_name,
        index=1,  # Will be looked up automatically
        state=InterfaceState.UP,
        interface_type=InterfaceType.WIRELESS,
        ip_address=IPv4Interface(f"{interface_ip}/24"),
    )
    
    # Test gateway (use interface's current gateway or a test gateway)
    test_gateway = IPv4Address("192.168.1.1")  # Common gateway
    
    # Setup interface routing (this should add main table route)
    success = await routing_manager._setup_interface_routing(
        interface_info, 
        routing_manager._get_table_id(interface_name),
        test_gateway
    )
    
    assert success, "Failed to setup interface routing"
    
    # Check that main table route was added
    assert interface_name in routing_manager.main_table_routes, \
        "Interface not tracked in main_table_routes"
    
    # Verify the route exists in main table
    routes_after = await get_main_table_default_routes()
    assert len(routes_after) > initial_count, \
        "No new route added to main table"
    
    # Test metric assignment logic
    metric = await routing_manager._get_main_table_metric()
    assert metric > 0, "Metric should be positive"
    assert metric >= 1024, "Metric should be reasonably high for lower priority"
    
    # Clean up
    await routing_manager._remove_main_table_routes(interface_name)
    
    # Verify cleanup worked
    routes_final = await get_main_table_default_routes()
    assert len(routes_final) == initial_count, \
        "Main table routes not properly cleaned up"
    
    logger.info("✓ Main table gateway management test passed")


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_main_table_host_route_management(routing_manager, available_interfaces):
    """Test adding host routes to main table for SIP tests"""
    interface_name = next(iter(available_interfaces))
    
    # Get current interface IP
    interface_ip = await get_interface_ip(interface_name)
    if not interface_ip:
        pytest.skip(f"Interface {interface_name} has no IP address")
    
    logger.info(f"Testing main table host routes on {interface_name}")
    
    test_host = "1.1.1.1"  # Cloudflare DNS
    
    # Add host route to main table (like SIP test does)
    success = await routing_manager.add_host_route(
        host_ip=test_host,
        interface_name=interface_name,
        table_id=254,  # Main table
        src_ip=interface_ip
    )
    
    assert success, f"Failed to add host route to main table"
    
    # Verify route exists in main table
    route_exists = await check_route_exists(f"{test_host}/32", table=254, src=interface_ip)
    assert route_exists, f"Host route {test_host}/32 not found in main table"
    
    # Track this route manually (since we bypassed _setup_interface_routing)
    if interface_name not in routing_manager.main_table_routes:
        routing_manager.main_table_routes[interface_name] = []
    
    routing_manager.main_table_routes[interface_name].append({
        "dst": f"{test_host}/32",
        "oif": 1,  # Will be looked up automatically
    })
    
    # Test cleanup
    await routing_manager._remove_main_table_routes(interface_name)
    
    # Verify cleanup worked (route should be gone)
    route_exists_after = await check_route_exists(f"{test_host}/32", table=254)
    assert not route_exists_after, f"Host route {test_host}/32 still exists after cleanup"
    
    logger.info("✓ Main table host route management test passed")


@pytest.mark.integration 
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_metric_assignment_logic(routing_manager):
    """Test the metric assignment logic for main table routes"""
    logger.info("Testing metric assignment logic")
    
    # Test with empty main table
    metric1 = await routing_manager._get_main_table_metric()
    assert metric1 >= 1124, f"Expected metric >= 1124, got {metric1}"  # 1024 + 100
    
    # Get current routes to understand the environment
    current_routes = await get_main_table_default_routes()
    logger.info(f"Current main table routes: {len(current_routes)}")
    
    if current_routes:
        min_metric = min(route['metric'] for route in current_routes)
        expected_metric = min_metric + 100
        
        # The metric should be 100 higher than the lowest existing
        assert metric1 >= expected_metric, \
            f"Metric {metric1} should be at least {expected_metric}"
    
    logger.info(f"✓ Metric assignment test passed (assigned metric: {metric1})")


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_comprehensive_cleanup(routing_manager, available_interfaces):
    """Test comprehensive cleanup of all managed routes"""
    interface_name = next(iter(available_interfaces))
    
    # Get current interface IP
    interface_ip = await get_interface_ip(interface_name)
    if not interface_ip:
        pytest.skip(f"Interface {interface_name} has no IP address")
    
    logger.info(f"Testing comprehensive cleanup on {interface_name}")
    
    # Get initial state
    initial_main_routes = await get_main_table_default_routes()
    initial_count = len(initial_main_routes)
    
    # Add multiple types of routes
    test_host1 = "8.8.8.8"
    test_host2 = "1.1.1.1"
    
    # 1. Add host route to dedicated table (ensure table ID exists first)
    table_id = routing_manager._get_table_id(interface_name)
    success1 = await routing_manager.add_host_route(test_host1, interface_name)
    assert success1, "Failed to add host route to dedicated table"
    
    # 2. Add host route to main table
    success2 = await routing_manager.add_host_route(
        test_host2, interface_name, table_id=254, src_ip=interface_ip
    )
    assert success2, "Failed to add host route to main table"
    
    # Track main table route for cleanup
    if interface_name not in routing_manager.main_table_routes:
        routing_manager.main_table_routes[interface_name] = []
    
    routing_manager.main_table_routes[interface_name].append({
        "dst": f"{test_host2}/32",
        "oif": 1,
    })
    
    # 3. Setup interface routing (adds gateway to main table)
    interface_info = InterfaceInfo(
        name=interface_name,
        index=1,
        state=InterfaceState.UP,
        interface_type=InterfaceType.WIRELESS,
        ip_address=IPv4Interface(f"{interface_ip}/24"),
    )
    
    test_gateway = IPv4Address("192.168.1.1")
    success3 = await routing_manager._setup_interface_routing(
        interface_info,
        routing_manager._get_table_id(interface_name),
        test_gateway
    )
    assert success3, "Failed to setup interface routing"
    
    # Verify routes were added
    table_id = routing_manager.interface_tables[interface_name]
    
    # Check dedicated table routes
    route1_exists = await check_route_exists(f"{test_host1}/32", table_id)
    assert route1_exists, f"Host route {test_host1} not in dedicated table"
    
    # Check main table routes  
    route2_exists = await check_route_exists(f"{test_host2}/32", table=254)
    assert route2_exists, f"Host route {test_host2} not in main table"
    
    # Check gateway was added to main table
    final_main_routes = await get_main_table_default_routes()
    assert len(final_main_routes) > initial_count, "Gateway not added to main table"
    
    # Now test comprehensive cleanup
    await routing_manager.remove_interface_routing(interface_name)
    
    # Verify cleanup worked
    # Main table should be back to initial state
    cleanup_main_routes = await get_main_table_default_routes()
    assert len(cleanup_main_routes) == initial_count, \
        f"Main table not cleaned up properly: {len(cleanup_main_routes)} vs {initial_count}"
    
    # Dedicated table routes should be gone (harder to verify in integration test)
    
    # Main table host route should be gone
    route2_exists_after = await check_route_exists(f"{test_host2}/32", table=254)
    assert not route2_exists_after, f"Main table host route {test_host2} not cleaned up"
    
    logger.info("✓ Comprehensive cleanup test passed")


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_routing_lifecycle(available_interfaces):
    """Test full lifecycle: setup -> add routes -> cleanup"""
    interface_name = next(iter(available_interfaces))
    
    # Get current interface IP
    interface_ip = await get_interface_ip(interface_name)
    if not interface_ip:
        pytest.skip(f"Interface {interface_name} has no IP address")
    
    logger.info(f"Testing full routing lifecycle on {interface_name}")
    
    # Create fresh routing manager
    manager = RoutingManager(base_table_id=9500)
    
    try:
        # Clean start
        await manager.startup_cleanup({interface_name})
        
        # Setup interface routing
        interface_info = InterfaceInfo(
            name=interface_name,
            index=1,
            state=InterfaceState.UP,
            interface_type=InterfaceType.WIRELESS,
            ip_address=IPv4Interface(f"{interface_ip}/24"),
        )
        
        gateway = IPv4Address("192.168.1.1")
        success = await manager.configure_interface_routing(interface_info, gateway)
        assert success, "Failed to configure interface routing"
        
        # Add host routes (simulating SIP test)
        sip_host = "192.0.2.100"  # RFC 5737 test address
        
        # Add to both main and dedicated tables
        success1 = await manager.add_host_route(
            sip_host, interface_name, table_id=254, src_ip=interface_ip
        )
        success2 = await manager.add_host_route(sip_host, interface_name)
        
        assert success1 and success2, "Failed to add SIP host routes"
        
        # Verify configuration
        assert interface_name in manager.configured_interfaces
        assert interface_name in manager.interface_tables
        assert interface_name in manager.main_table_routes
        
        # Remove interface routing
        cleanup_success = await manager.remove_interface_routing(interface_name)
        assert cleanup_success, "Failed to remove interface routing"
        
        # Verify cleanup
        assert interface_name not in manager.configured_interfaces
        assert interface_name not in manager.main_table_routes
        
        logger.info("✓ Full routing lifecycle test passed")
        
    finally:
        # Final cleanup
        await manager.cleanup()


# Standalone test runner for manual execution
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def run_standalone_tests():
        """Run tests manually for debugging"""
        print("Running enhanced routing integration tests...")
        
        # Get available interfaces
        interfaces = get_available_wireless_interfaces()
        if not interfaces:
            print("❌ No wireless interfaces found - skipping tests")
            return
        
        print(f"Found wireless interfaces: {interfaces}")
        
        # Create routing manager
        manager = RoutingManager(base_table_id=9000)
        
        try:
            interface_name = next(iter(interfaces))
            interface_ip = await get_interface_ip(interface_name)
            
            if not interface_ip:
                print(f"❌ Interface {interface_name} has no IP - skipping tests")
                return
            
            print(f"Testing on {interface_name} with IP {interface_ip}")
            
            # Test 1: Host route with source IP
            print("\n1. Testing host route with source IP...")
            success = await manager.add_host_route("8.8.8.8", interface_name)
            if success:
                print("✓ Host route added successfully")
                await manager.remove_host_route("8.8.8.8", interface_name)
                print("✓ Host route removed successfully")
            else:
                print("❌ Host route test failed")
            
            # Test 2: Metric assignment
            print("\n2. Testing metric assignment...")
            metric = await manager._get_main_table_metric()
            print(f"✓ Assigned metric: {metric}")
            
            print("\n✅ Standalone tests completed")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            
        finally:
            await manager.cleanup()
    
    asyncio.run(run_standalone_tests())