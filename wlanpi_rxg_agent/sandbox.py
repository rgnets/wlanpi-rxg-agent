import logging
import signal
import sys
import asyncio

from wlanpi_rxg_agent.lib.logging_utils import setup_logging
from wlanpi_rxg_agent.lib.network_control import NetworkControlManager

# Setup logging with custom formatter
setup_logging(level=logging.DEBUG)

logger = logging.getLogger(__name__)

# Global reference to the manager for signal handling
manager = None


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def sync_signal_handler(signum, _):
        """Synchronous signal handler that initiates shutdown"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        # Set a flag or raise KeyboardInterrupt to break the main loop
        raise KeyboardInterrupt()
    
    signal.signal(signal.SIGINT, sync_signal_handler)
    signal.signal(signal.SIGTERM, sync_signal_handler)


async def main():
    """Main function that runs the NetworkControlManager until interrupted"""
    global manager
    
    logger.info("Starting Network Control Manager sandbox")
    logger.info("Press Ctrl+C to stop monitoring")
    
    # Setup signal handlers
    setup_signal_handlers()
    
    try:
        # Create manager for specific wireless interfaces
        # You can modify this set to include the wireless interfaces you want to monitor
        wireless_interfaces = {'wlan0', 'wlan1', 'wlan2', 'wlan3'}
        manager = NetworkControlManager(wireless_interfaces=wireless_interfaces)
        
        logger.info(f"Monitoring wireless interfaces: {wireless_interfaces}")
        
        # Start monitoring
        await manager.start()
        
        logger.info("Network Control Manager started successfully")
        logger.info("Try the following to test:")
        logger.info("- Bring interfaces up/down: sudo ip link set wlan0 up/down")
        logger.info("- Connect to networks to trigger DHCP")
        logger.info("- Check routing tables: ip route show table all")
        logger.info("- Check IP rules: ip rule show")
        
        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as error:
        logger.error(f"Unexpected error: {error}")
    finally:
        # Clean shutdown
        if manager:
            logger.info("Stopping Network Control Manager...")
            await manager.stop()
            logger.info("Network Control Manager stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)