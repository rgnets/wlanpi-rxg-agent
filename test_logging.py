#!/usr/bin/env python3
"""
Test script to verify colored logging functionality
"""
import logging
from wlanpi_rxg_agent.lib.logging_utils import setup_logging, supports_color

# Test the setup
print(f"Color support detected: {supports_color()}")

# Setup logging
setup_logging(level=logging.DEBUG)

logger = logging.getLogger(__name__)

# Test all log levels
logger.debug("This is a DEBUG message")
logger.info("This is an INFO message")
logger.warning("This is a WARNING message")
logger.error("This is an ERROR message")
logger.critical("This is a CRITICAL message")

print("Logging test completed!")