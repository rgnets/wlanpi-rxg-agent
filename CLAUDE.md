# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Testing
```bash
# Run unit tests with coverage
./scripts/test.sh
pytest --cov=app --cov-report=term-missing wlanpi_rxg_agent/tests

# Run test coverage with HTML output
./scripts/test-cov-html.sh

# Run integration tests (requires hardware/system permissions)
./scripts/test-integration.sh

# Run specific test categories
pytest wlanpi_rxg_agent/tests/integration/  # Integration tests only
pytest -m "not hardware"                    # Skip hardware-dependent tests
pytest -m "not slow"                        # Skip slow tests
```

### Code Quality
```bash
# Format code (autoflake, black, isort)
./scripts/format.sh

# Lint code (mypy, black check, isort check, flake8)
./scripts/lint.sh

# Individual linting tools
mypy wlanpi_rxg_agent
black wlanpi_rxg_agent --check
isort --check-only wlanpi_rxg_agent
flake8 wlanpi_rxg_agent
```

### Building
```bash
# Build application
python -m build

# Build baresip dependencies (requires system packages). Should only be run manually on a remote raspberry pi.
./build_baresip.sh

# Setup development environment on a raspberry pi, not the local machine. Should only be run manually.
./scripts/setup_dev.sh

# Generate requirements files
./scripts/generate_requirements.sh
```

### Running

All code is executed on a remote Raspberry Pi Compute Module 4, via SSH, with a tmp directory synced from PyCharm and a virtualenv. An example of running a python snippet on that device follows:
```bash
   ssh wlanpi@dev-wlanpi2 "cd /tmp/pycharm_project_577 && source ~/.virtualenvs/wlanpi-rxg-agent/bin/activate && python -c 'print(\"Hello\")'"  
```
```bash
# Run as FastAPI application (development)
python -m wlanpi_rxg_agent

# Run as daemon
python -m wlanpi_rxg_agent.the_daemon

# Run with uvicorn directly
uvicorn wlanpi_rxg_agent.rxg_agent:app --host 0.0.0.0 --port 8200
```

## Architecture Overview

### Core Components

**Main Application (`rxg_agent.py`)**: FastAPI-based application that orchestrates all components using an event-driven architecture with message and command buses.

**Event Bus System (`lib/event_bus/`)**: Central communication mechanism using separate message and command buses for decoupled component interaction.

**RXG Agent (`RXGAgent` class)**: Main orchestrator that manages bridge configuration, handles certified connections, and coordinates component lifecycle.

**Supplicant (`lib/rxg_supplicant/`)**: Handles authentication and registration with RXG servers, manages certificate-based connections, and tracks connection state through `RxgSupplicantState` enum.

**WiFi Control (`lib/wifi_control/`)**: Manages wireless interface configuration using WPA supplicant integration for network connection management.

**SIP Control (`lib/sip_control/`)**: Implements SIP testing capabilities using baresip library integration with custom RG Nets modules.

**Network Control (`lib/network_control/`)**: Comprehensive async network interface management system using pyroute2. Monitors wireless interfaces via netlink, automatically configures source-based routing tables, manages DHCP clients, and ensures packets originating from each interface's IP address leave only through that interface. Key components:
- `NetworkControlManager`: Main coordinator for interface monitoring and configuration
- `AsyncNetlinkMonitor`: Real-time netlink monitoring for interface state changes
- `RoutingManager`: Hybrid routing table and IP rule management using AsyncIPRoute (for dedicated tables) and NDB (for main table default routes). This approach resolves AsyncIPRoute limitations with multiple default routes while maintaining compatibility.
- `DHCPClient`: Handles DHCP client operations and lease management
- `DHCPLeaseParser`: Parses DHCP lease files for network configuration

**Tasker (`lib/tasker/`)**: Provides task scheduling and execution framework with support for repeating and one-shot tasks.

### Key Design Patterns

- **Event-Driven Architecture**: Components communicate through domain events via message/command buses
- **Async/Await**: Extensive use of asyncio for concurrent operations
- **Configuration Management**: TOML-based configuration with automatic loading and validation
- **State Management**: Explicit state tracking for supplicant and connection states
- **Dependency Injection**: Components are initialized and wired in the FastAPI lifespan

### Important Files

- `rxg_agent.py`: Main application entry point with FastAPI setup
- `busses.py`: Event bus instances for inter-component communication
- `lib/domain.py`: Domain events and messages
- `lib/*/domain.py`: Component-specific domain models and events
- `bridge_control.py`: MQTT bridge service management
- `certificate_tool.py`: Certificate management utilities

### Configuration

The application uses TOML configuration files:
- Agent configuration: Managed by `AgentConfigFile`
- Bridge configuration: Managed by `BridgeConfigFile`
- Default config location: `install/etc/wlanpi-rxg-agent/config.toml`

### Dependencies

Key external dependencies:
- `fastapi` + `uvicorn`: Web framework and ASGI server
- `aiomqtt`, `paho_mqtt`: MQTT communication
- `wpa_supplicant`: WiFi management
- `baresipy`: SIP protocol implementation
- `pyroute2`: Network routing control
- `pydantic-settings`: Configuration management
- `apscheduler`: Task scheduling

## Testing Structure

### Test Organization

The project uses a structured testing approach with separate test categories:

- **Unit Tests** (`wlanpi_rxg_agent/lib/*/tests/`): Component-specific unit tests
- **Integration Tests** (`wlanpi_rxg_agent/tests/integration/`): Device-based functionality tests
- **Hardware Tests**: Tests requiring actual hardware interfaces and system permissions

### Integration Tests

Integration tests are designed to run on actual Raspberry Pi hardware and test real system interactions:

- **Network Control Tests** (`test_network_control_*.py`): 
  - WiFi connectivity loss detection
  - Netlink monitoring with real interfaces
  - Hardware interface discovery and management
  
- **Test Markers**:
  - `@pytest.mark.integration`: General integration tests
  - `@pytest.mark.hardware`: Tests requiring actual hardware
  - `@pytest.mark.slow`: Long-running tests (can be skipped)

### Running Integration Tests

```bash
# Run all integration tests on device
ssh wlanpi@dev-wlanpi2 "cd /tmp/pycharm_project_577 && source ~/.virtualenvs/wlanpi-rxg-agent/bin/activate && ./scripts/test-integration.sh"

# Run specific test categories
pytest wlanpi_rxg_agent/tests/integration/test_network_control_connectivity_loss.py  # Connectivity tests
pytest -m hardware                                                                   # Hardware tests only
pytest -m "integration and not slow"                                                # Integration tests excluding slow ones
```

### Test Requirements

Integration tests require:
- Linux system with wireless interfaces
- System permissions for network configuration (root or CAP_NET_ADMIN)
- Access to netlink, DHCP, and wireless subsystems
- Wireless interfaces (wlan0, wlan1, etc.) for testing

## Memories

### Testing Guidance
- Any major, reusable integration tests should be added to our tests/integration directory so we can use them later.

### Remote Development
- You usually need to add a PYTHON_PATH with the remote project directory when running python snippets in the remote virtualenv.

### Routing System Changes
- **Hybrid Routing Manager**: The routing manager now uses a hybrid approach to handle AsyncIPRoute limitations with multiple default routes in the main table (254). 
- **AsyncIPRoute**: Used for dedicated routing tables (fast, reliable) - ~0.0034s avg operation time
- **NDB**: Used specifically for main table default route additions (handles multiple default routes correctly) - ~0.0864s avg operation time
- **Performance Trade-off**: NDB is ~25x slower than AsyncIPRoute, but only used for infrequent main table operations
- **Thread Pool**: NDB operations run in a thread pool to avoid asyncio event loop conflicts
- **Backward Compatibility**: All existing API methods preserved, integration tests continue to pass