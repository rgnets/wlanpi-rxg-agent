import logging
import os
from collections import defaultdict
from os import PathLike
from typing import Union

import toml

CONFIG_DIR = "/etc/wlanpi-rxg-agent"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"
BRIDGE_CONFIG_FILE = os.path.join(BRIDGE_CONFIG_DIR, "config.toml")


class ConfigurationManager:

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

    async def set_fallback_rxg(self, fallback_rxg: str):
        pass

    async def set_override_rxg(self, fallback_rxg: str):
        pass

    async def set_bootloader_address(self, address: str):
        pass
