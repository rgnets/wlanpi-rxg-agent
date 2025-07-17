"""
Pytest configuration and shared fixtures for wlanpi-rxg-agent tests
"""
import pytest
import asyncio
import logging
from typing import Set

from wlanpi_rxg_agent.lib.logging_utils import setup_logging


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def setup_test_logging():
    """Setup logging for tests with appropriate levels"""
    setup_logging(level=logging.INFO)
    
    # Reduce noise from common libraries
    logging.getLogger("pyroute2.netlink.core").setLevel(logging.WARNING)
    logging.getLogger("pyroute2.ndb").setLevel(logging.WARNING)


@pytest.fixture
def wireless_interfaces() -> Set[str]:
    """Default set of wireless interfaces for testing"""
    return {'wlan0', 'wlan1', 'wlan2', 'wlan3'}


@pytest.fixture
def test_interface_name() -> str:
    """Default test interface name"""
    return 'wlan0'