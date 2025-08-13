import os
# print(os.environ)
RUNTIME_ENV = os.environ.get("RUNTIME_ENV", "production")
IS_DEV = RUNTIME_ENV == "development"

CONFIG_DIR = "/etc/wlanpi-rxg-agent"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"
BRIDGE_CONFIG_FILE = os.path.join(BRIDGE_CONFIG_DIR, "config.toml")
BARESIP_DEBUG_OUTPUT = True
