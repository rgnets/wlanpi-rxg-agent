"""
Hardware integration tests for NetworkControlManager

These tests interact with real network interfaces and require:
- Root or CAP_NET_ADMIN permissions
- Actual wireless interfaces
- Ability to manipulate network configuration

Use with caution on production systems.
"""
import pytest
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Set, List

from wlanpi_rxg_agent.lib.network_control import NetworkControlManager
from wlanpi_rxg_agent.lib.network_control.netlink_monitor import AsyncNetlinkMonitor

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
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(cmd)}")
        logger.error(f"Return code: {e.returncode}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        raise


@pytest.fixture
def available_wireless_interfaces():
    """Fixture providing actually available wireless interfaces"""
    interfaces = get_available_wireless_interfaces()
    if not interfaces:
        pytest.skip("No wireless interfaces available for testing")
    return interfaces


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_netlink_monitor_real_interfaces(available_wireless_interfaces):
    """Test netlink monitor with real wireless interfaces"""
    
    monitor = AsyncNetlinkMonitor(wireless_interfaces=available_wireless_interfaces)
    
    events_received = []
    
    async def event_callback(event_type, msg, interface_info):
        events_received.append((event_type, interface_info))
        logger.info(f"Received {event_type} for {interface_info.name if interface_info else 'unknown'}")
    
    monitor.add_callback(event_callback)
    
    try:
        await monitor.start()
        
        # Let it run for a short time to capture any existing state
        await asyncio.sleep(1.0)
        
        # Monitor should be running without errors
        assert monitor.running, "Monitor should be running"
        
        logger.info(f"Monitor successfully started with {len(available_wireless_interfaces)} interfaces")
        
    finally:
        await monitor.stop()
    
    assert not monitor.running, "Monitor should be stopped"


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_network_manager_with_real_interfaces(available_wireless_interfaces):
    """Test NetworkControlManager with real wireless interfaces"""
    
    # Use only first interface to avoid too much system interaction
    test_interfaces = {list(available_wireless_interfaces)[0]}
    
    manager = NetworkControlManager(wireless_interfaces=test_interfaces)
    
    try:
        await manager.start()
        
        # Manager should start successfully
        assert manager.running, "NetworkControlManager should be running"
        
        # Let it discover interfaces
        await asyncio.sleep(1.0)
        
        # Check that it discovered the interface
        interface_name = list(test_interfaces)[0]
        assert interface_name in manager.managed_interfaces, f"Interface {interface_name} should be managed"
        
        interface_info = manager.managed_interfaces[interface_name]
        logger.info(f"Discovered interface: {interface_info.name}, state: {interface_info.state}")
        
    finally:
        await manager.stop()
    
    assert not manager.running, "NetworkControlManager should be stopped"


@pytest.mark.integration
@pytest.mark.hardware
@pytest.mark.skipif(
    not Path("/sys/class/net/wlan0").exists(),
    reason="wlan0 interface not available"
)
@pytest.mark.asyncio
async def test_interface_info_gathering():
    """Test gathering real interface information"""
    
    monitor = AsyncNetlinkMonitor()
    interface_info = await monitor._get_interface_info("wlan0")
    
    if interface_info:
        logger.info(f"wlan0 info: {interface_info}")
        
        # Basic validation
        assert interface_info.name == "wlan0"
        assert interface_info.index > 0
        assert interface_info.interface_type.value in ["wireless", "other"]
        
        if interface_info.mac_address:
            # MAC address should be in standard format
            assert len(interface_info.mac_address.split(":")) == 6
        
        logger.info(f"Successfully gathered info for wlan0: state={interface_info.state}")
    else:
        pytest.skip("Could not gather wlan0 interface information")


@pytest.mark.integration
@pytest.mark.hardware
def test_system_requirements():
    """Test that system requirements for network control are met"""
    
    # Check for required system paths
    required_paths = [
        "/sys/class/net",
        "/proc/net/route",
        "/var/lib/dhcp",
    ]
    
    for path in required_paths:
        assert Path(path).exists(), f"Required system path {path} not found"
    
    # Check for required system commands
    required_commands = ["ip", "dhclient"]
    
    for cmd in required_commands:
        try:
            result = subprocess.run(["which", cmd], capture_output=True, text=True)
            assert result.returncode == 0, f"Required command '{cmd}' not found in PATH"
        except Exception as e:
            pytest.fail(f"Could not check for command '{cmd}': {e}")
    
    logger.info("All system requirements satisfied")


@pytest.mark.integration  
@pytest.mark.hardware
@pytest.mark.slow
@pytest.mark.asyncio
async def test_extended_monitoring(available_wireless_interfaces):
    """Extended test that monitors interfaces for a longer period"""
    
    # This test runs for 30 seconds to catch real network events
    # Mark as 'slow' so it can be skipped in quick test runs
    
    monitor = AsyncNetlinkMonitor(wireless_interfaces=available_wireless_interfaces)
    
    events_received = []
    
    async def event_callback(event_type, msg, interface_info):
        events_received.append({
            'timestamp': asyncio.get_event_loop().time(),
            'event_type': event_type,
            'interface': interface_info.name if interface_info else None,
            'state': interface_info.state.value if interface_info else None
        })
        logger.info(f"Event: {event_type} for {interface_info.name if interface_info else 'unknown'}")
    
    monitor.add_callback(event_callback)
    
    try:
        await monitor.start()
        logger.info("Starting extended monitoring for 30 seconds...")
        logger.info("Try manipulating wireless interfaces during this time:")
        logger.info("  sudo ip link set wlan0 down")  
        logger.info("  sudo ip link set wlan0 up")
        
        # Monitor for 30 seconds
        await asyncio.sleep(30.0)
        
    finally:
        await monitor.stop()
    
    logger.info(f"Extended monitoring completed. Captured {len(events_received)} events:")
    for event in events_received:
        logger.info(f"  {event}")
    
    # The test passes regardless of events captured, since network events are unpredictable