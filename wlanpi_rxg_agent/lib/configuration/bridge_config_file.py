import os

from lib.configuration.config_file import ConfigFile

BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"


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


if __name__ == "__main__":
    boot = BridgeConfigFile()
    boot.load()
    print(boot.data)