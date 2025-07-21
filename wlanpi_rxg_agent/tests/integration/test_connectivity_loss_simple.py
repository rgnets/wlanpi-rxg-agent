"""
Simple integration test for WiFi connectivity loss detection

This test verifies the basic functionality without complex fixtures.
"""

import asyncio
import logging
from typing import Any, List

from wlanpi_rxg_agent.busses import message_bus
from wlanpi_rxg_agent.lib.network_control import NetworkControlManager
from wlanpi_rxg_agent.lib.network_control.domain import Messages as NetworkMessages
from wlanpi_rxg_agent.lib.wifi_control.domain import Messages as WiFiMessages

logger = logging.getLogger(__name__)


def test_connectivity_loss_integration():
    """Integration test for WiFi connectivity loss detection"""

    async def run_test():
        # Track events
        events_received = []

        def track_event(event):
            events_received.append(event)
            logger.info(f"Received event: {type(event).__name__}")

        # Setup event tracking
        message_bus.add_handler(NetworkMessages.ConnectivityLost, track_event)

        try:
            # Create and start network manager
            wireless_interfaces = {"wlan0", "wlan1"}
            manager = NetworkControlManager(wireless_interfaces=wireless_interfaces)
            await manager.start()

            try:
                logger.info("Testing WiFi disconnection event...")

                # Simulate WiFi disconnection
                disconnect_event = WiFiMessages.Disconnection(interface="wlan0")
                message_bus.handle(disconnect_event)

                # Allow event processing
                await asyncio.sleep(0.2)

                # Verify connectivity lost event was emitted
                connectivity_lost_events = [
                    e
                    for e in events_received
                    if isinstance(e, NetworkMessages.ConnectivityLost)
                ]

                if len(connectivity_lost_events) > 0:
                    logger.info(
                        f"✓ SUCCESS: Received {len(connectivity_lost_events)} ConnectivityLost events"
                    )
                    event = connectivity_lost_events[0]
                    logger.info(f"  Interface: {event.interface.name}")
                    logger.info(
                        f"  State reset: IP={event.interface.ip_address}, Gateway={event.interface.gateway}"
                    )
                    return True
                else:
                    logger.error("✗ FAILURE: No ConnectivityLost events received")
                    return False

            finally:
                await manager.stop()

        finally:
            # Cleanup event handlers
            if (
                hasattr(message_bus, "_handlers")
                and NetworkMessages.ConnectivityLost in message_bus._handlers
            ):
                if hasattr(
                    message_bus._handlers[NetworkMessages.ConnectivityLost], "remove"
                ):
                    message_bus._handlers[NetworkMessages.ConnectivityLost].remove(
                        track_event
                    )
                elif hasattr(
                    message_bus._handlers[NetworkMessages.ConnectivityLost], "discard"
                ):
                    message_bus._handlers[NetworkMessages.ConnectivityLost].discard(
                        track_event
                    )

    # Run the async test
    result = asyncio.run(run_test())
    assert result, "Connectivity loss detection test failed"


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/tmp/pycharm_project_577")

    # Setup logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    try:
        test_connectivity_loss_integration()
        print("✓ Integration test PASSED")
    except Exception as e:
        print(f"✗ Integration test FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
