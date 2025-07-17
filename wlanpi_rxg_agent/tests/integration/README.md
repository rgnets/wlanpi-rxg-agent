# Integration Tests for WLAN Pi RXG Agent

This directory contains integration tests designed to run on actual Raspberry Pi hardware and test real system interactions.

## Test Categories

### Network Control Tests
- **`test_simple_connectivity_loss.py`**: Tests WiFi connectivity loss detection and cleanup
- **`test_network_control_hardware.py`**: Tests hardware interaction with real network interfaces
- **`test_connectivity_loss_simple.py`**: Standalone test script (can run directly with Python)

### Test Markers
- `@pytest.mark.integration`: General integration tests
- `@pytest.mark.hardware`: Tests requiring actual hardware interfaces  
- `@pytest.mark.slow`: Long-running tests (can be skipped)

## Running Tests

### Prerequisites
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Ensure proper permissions for network operations
# Tests may require root or CAP_NET_ADMIN capabilities
```

### On Target Device (Raspberry Pi)
```bash
# Run all integration tests
./scripts/test-integration.sh

# Run specific test file
python -m pytest wlanpi_rxg_agent/tests/integration/test_simple_connectivity_loss.py -v

# Run standalone test
python wlanpi_rxg_agent/tests/integration/test_connectivity_loss_simple.py

# Skip hardware-dependent tests
pytest -m "integration and not hardware"

# Skip slow tests
pytest -m "integration and not slow"
```

### Via SSH
```bash
ssh wlanpi@dev-wlanpi2 "cd /tmp/pycharm_project_577 && source ~/.virtualenvs/wlanpi-rxg-agent/bin/activate && ./scripts/test-integration.sh"
```

## What These Tests Verify

### WiFi Connectivity Loss Detection (`test_simple_connectivity_loss.py`)
✅ **WiFi Disconnection Events**: Verifies that WiFi disconnection events trigger proper cleanup  
✅ **State Change Detection**: Tests different WPA supplicant state changes (`disconnected`, `inactive`, `interface_disabled`)  
✅ **Route Cleanup**: Confirms routing tables and DHCP clients are properly cleaned up  
✅ **Event Bus Integration**: Validates `ConnectivityLost` events are emitted correctly  
✅ **Interface State Reset**: Ensures IP addresses, gateways, and DHCP lease flags are reset  

### Hardware Integration (`test_network_control_hardware.py`)  
✅ **Real Interface Discovery**: Tests detection of actual wireless interfaces  
✅ **Netlink Monitoring**: Verifies real-time netlink event monitoring  
✅ **System Requirements**: Checks for required system paths and commands  
✅ **Extended Monitoring**: Long-running tests for manual interface manipulation  

## Test Requirements

### System Requirements
- Linux system with `/sys/class/net` interface information
- Wireless network interfaces (wlan0, wlan1, etc.)
- Network configuration tools (`ip`, `dhclient`)
- Python 3.9+ with asyncio support

### Permissions
Some tests may require elevated permissions for:
- Network interface manipulation
- Routing table modifications  
- DHCP client operations
- Netlink socket access

### Hardware
- Actual wireless interfaces for hardware tests
- Raspberry Pi Compute Module 4 (target platform)
- Working network environment for extended tests

## Test Output

Integration tests provide detailed logging showing:
```
INFO - Initializing network control components
INFO - Testing WiFi disconnection event...
INFO - WiFi disconnection detected on wlan0
INFO - Cleaning up wlan0 after WiFi disconnect
INFO - Stopped DHCP client for wlan0
INFO - Received event: ConnectivityLost
INFO - ✓ SUCCESS: Connectivity loss detection working correctly
```

## Troubleshooting

### Common Issues
1. **Missing wireless interfaces**: Tests will skip or warn if no `wlan*` interfaces found
2. **Permission errors**: Some tests require root or network capabilities
3. **Import errors**: Ensure `PYTHONPATH` includes project root
4. **Event bus conflicts**: Avoid running multiple tests simultaneously

### Debug Mode
```bash
# Run with verbose logging
python -m pytest wlanpi_rxg_agent/tests/integration/ -v --log-cli-level=DEBUG

# Run individual test for debugging
python wlanpi_rxg_agent/tests/integration/test_connectivity_loss_simple.py
```