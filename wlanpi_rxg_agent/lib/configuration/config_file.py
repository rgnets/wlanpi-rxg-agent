import logging
import os
from collections import defaultdict
from os import PathLike
from typing import Union

import toml

from utils import run_command

AGENT_CONFIG_DIR = "/etc/wlanpi-rxg-agent"
BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"

class ConfigFile():

    def __init__(self, config_file:Union[str, PathLike] = "config.toml"):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        self.config_file = config_file
        self.data:dict[str,dict] = defaultdict(dict)

    def load(self):
        try:
            self.data = toml.load(self.config_file)
            self.logger.debug("Existing config loaded.")
        except toml.decoder.TomlDecodeError as e:
            self.logger.warning(
                f"Unable to decode existing config. Error: {e.msg}"
            )
            raise e

    def save(self):
        with open(self.config_file, "w") as f:
            toml.dump(self.data, f)

    def create_defaults(self):
        self.data = defaultdict(dict)

    def load_or_create_defaults(self):
        try:
            self.load()
        except toml.decoder.TomlDecodeError as e:
            self.create_defaults()
            self.logger.warning(
                f"Unable to decode existing config, using defaults. Error: {e.msg}"
            )

class BridgeConfigFile(ConfigFile):

    def __init__(self):
        super().__init__(os.path.join(BRIDGE_CONFIG_DIR, "config.toml"))

    def create_defaults(self):
        self.data = {
            "MQTT": {
                "server": "192.168.6.1",
                "port": 1883,
            },
            "MQTT_TLS": {
                "use_tls": False,
                "ca_certs": None,
                "certfile": None,
                "keyfile": None,
                "cert_reqs": 2
            }
        }

class AgentConfigFile(ConfigFile):
    def __init__(self):
        super().__init__(os.path.join(AGENT_CONFIG_DIR, "config.toml"))

    def create_defaults(self):
        self.data = {
            "General": {
                "override_rxg": "",
                "fallback_rxg": "",
            }
        }


class BootloaderConfigFile(ConfigFile):
    def __init__(self):
        self.data_part_path = "/dev/mmcblk0p1"
        super().__init__("/mnt/bldata.json")


    def load(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False)
            super().load()
            run_command(f"umount {self.data_part_path}", shell=True, use_shlex=False)


    def save(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False)
            super().save()
            run_command(f"umount {self.data_part_path}", shell=True, use_shlex=False)

    def load_or_create_defaults(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False)
            super().load_or_create_defaults()
            run_command(f"umount {self.data_part_path}", shell=True, use_shlex=False)

    def create_defaults(self):
        self.data = {
            "current_image_md5": "2c84fecee801b51cedea18015e9abfea",
            "last_flash_success": True,
            "boot_exec_times": [],
            "first_boot": True,
            "remote_log": True,
            "boot_server_override": None,
            "boot_server_fallback": "piglet.rgnets.com",
            "device_type": "wlanpi",
        }

    @staticmethod
    def simulate_config() -> object:
        return {
            "current_image_md5": "2c84fecee801b51cedea18015e9abfea",
            "last_flash_success": True,
            "boot_exec_times": [],
            "first_boot": True,
            "remote_log": True,
            "boot_server_override": None,
            "boot_server_fallback": "piglet.rgnets.com",
            "device_type": "wlanpi",
        }

    @staticmethod
    def count_partitions() -> int:
        return int(run_command("ls -l /dev/mmcblk0p* | wc -l", shell=True, use_shlex=False).stdout.strip())


