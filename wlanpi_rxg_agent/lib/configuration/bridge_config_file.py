import logging
import os

from wlanpi_rxg_agent.lib.configuration.config_file import ConfigFile

BRIDGE_CONFIG_DIR = "/tmp/etc/wlanpi-mqtt-bridge"


class BridgeConfigFile(ConfigFile):
    def __init__(self):
        super().__init__(os.path.join(BRIDGE_CONFIG_DIR, "config.toml"), defaults = {
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
        })


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.INFO)
    boot = BridgeConfigFile()
    boot.load_or_create_defaults()
    boot.save()
    print(boot.data)