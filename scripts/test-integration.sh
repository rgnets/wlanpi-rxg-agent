#!/bin/bash
set -e

echo "Running integration tests for wlanpi-rxg-agent..."
echo "These tests require actual hardware and system permissions."
echo

# Check if we're running on the target device
if [[ ! -d "/sys/class/net" ]]; then
    echo "WARNING: /sys/class/net not found. Are you running on a Linux system?"
fi

# Check for wireless interfaces
wireless_count=$(ls /sys/class/net/ | grep -c "^wlan" || true)
if [[ $wireless_count -eq 0 ]]; then
    echo "WARNING: No wireless interfaces found. Some tests may fail."
else
    echo "Found $wireless_count wireless interfaces"
fi

echo
echo "Running integration tests..."

# Set up Python path for imports
export PYTHONPATH="$(pwd):$PYTHONPATH"

# Run integration tests with verbose output
python -m pytest wlanpi_rxg_agent/tests/integration/ \
    -m integration \
    --verbose \
    --tb=short \
    --log-cli-level=INFO \
    --log-cli-format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s" \
    "$@"

echo
echo "Integration tests completed."