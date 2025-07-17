"""
Simple pytest-compatible integration test for WiFi connectivity loss detection
"""
import pytest
import asyncio
import logging

from wlanpi_rxg_agent.lib.network_control import NetworkControlManager
from wlanpi_rxg_agent.busses import message_bus
from wlanpi_rxg_agent.lib.wifi_control.domain import Messages as WiFiMessages
from wlanpi_rxg_agent.lib.network_control.domain import Messages as NetworkMessages

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simple_connectivity_loss():
    """Simple integration test for WiFi connectivity loss detection"""
    
    # Track events
    events_received = []
    
    def track_event(event):
        events_received.append(event)
        logger.info(f"Received event: {type(event).__name__}")
    
    # Setup event tracking
    message_bus.add_handler(NetworkMessages.ConnectivityLost, track_event)
    
    try:
        # Create and start network manager
        wireless_interfaces = {'wlan0', 'wlan1'}
        manager = NetworkControlManager(wireless_interfaces=wireless_interfaces)
        await manager.start()
        
        try:
            logger.info("Testing WiFi disconnection event...")
            
            # Simulate WiFi disconnection
            disconnect_event = WiFiMessages.Disconnection(interface='wlan0')
            message_bus.handle(disconnect_event)
            
            # Allow event processing
            await asyncio.sleep(0.2)
            
            # Verify connectivity lost event was emitted
            connectivity_lost_events = [e for e in events_received if isinstance(e, NetworkMessages.ConnectivityLost)]
            
            assert len(connectivity_lost_events) > 0, "Expected ConnectivityLost event to be emitted"
            
            event = connectivity_lost_events[0]
            assert event.interface.name == 'wlan0', f"Expected event for wlan0, got {event.interface.name}"
            assert event.interface.ip_address is None, "IP address should be reset to None"
            assert event.interface.gateway is None, "Gateway should be reset to None"
            assert event.interface.has_dhcp_lease is False, "DHCP lease flag should be reset to False"
            
            logger.info(f"✓ SUCCESS: Connectivity loss detection working correctly")
                
        finally:
            await manager.stop()
            
    finally:
        # Cleanup event handlers - handle different message bus implementations
        try:
            if hasattr(message_bus, '_handlers') and NetworkMessages.ConnectivityLost in message_bus._handlers:
                handlers = message_bus._handlers[NetworkMessages.ConnectivityLost]
                if hasattr(handlers, 'remove') and track_event in handlers:
                    handlers.remove(track_event)
                elif hasattr(handlers, 'discard'):
                    handlers.discard(track_event)
        except (AttributeError, ValueError):
            # Event handler cleanup failed, but test succeeded
            pass


@pytest.mark.integration  
def test_wifi_state_change_types():
    """Test different WiFi state change types trigger connectivity loss"""
    
    async def run_test():
        events_received = []
        
        def track_event(event):
            events_received.append(event)
        
        message_bus.add_handler(NetworkMessages.ConnectivityLost, track_event)
        
        try:
            wireless_interfaces = {'wlan0'}
            manager = NetworkControlManager(wireless_interfaces=wireless_interfaces)
            await manager.start()
            
            try:
                # Test different state changes that should trigger cleanup
                disconnecting_states = ['disconnected', 'inactive', 'interface_disabled']
                
                for state in disconnecting_states:
                    state_change_event = WiFiMessages.WpaSupplicantStateChanged(
                        interface='wlan0',
                        state=state
                    )
                    message_bus.handle(state_change_event)
                    await asyncio.sleep(0.1)
                
                # Test a connecting state that should NOT trigger cleanup
                connecting_event = WiFiMessages.WpaSupplicantStateChanged(
                    interface='wlan0',
                    state='completed'
                )
                message_bus.handle(connecting_event)
                await asyncio.sleep(0.1)
                
                # Count connectivity lost events (should be 3, not 4)
                connectivity_lost_events = [e for e in events_received if isinstance(e, NetworkMessages.ConnectivityLost)]
                
                assert len(connectivity_lost_events) == len(disconnecting_states), \
                    f"Expected {len(disconnecting_states)} events, got {len(connectivity_lost_events)}"
                
                logger.info(f"✓ SUCCESS: State change detection working correctly ({len(connectivity_lost_events)} events)")
                
            finally:
                await manager.stop()
                
        finally:
            # Cleanup
            try:
                if hasattr(message_bus, '_handlers') and NetworkMessages.ConnectivityLost in message_bus._handlers:
                    handlers = message_bus._handlers[NetworkMessages.ConnectivityLost]
                    if hasattr(handlers, 'remove') and track_event in handlers:
                        handlers.remove(track_event)
                    elif hasattr(handlers, 'discard'):
                        handlers.discard(track_event)
            except (AttributeError, ValueError):
                pass
    
    # Run async test from sync function
    result = asyncio.run(run_test())