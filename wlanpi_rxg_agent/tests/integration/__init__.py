"""
Integration tests for wlanpi-rxg-agent

These tests are designed to run on actual hardware and test real system
interactions. They require:
- Linux network namespaces or actual wireless interfaces
- System permissions for network configuration
- Access to netlink, DHCP, and wireless subsystems

Run with: python -m pytest wlanpi_rxg_agent/tests/integration/
"""
