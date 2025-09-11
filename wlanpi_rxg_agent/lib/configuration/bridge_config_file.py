import logging
import os

from wlanpi_rxg_agent.lib.configuration.config_file import ConfigFile
from wlanpi_rxg_agent.lib.configuration.schemas import BridgeConfig

BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"


class BridgeConfigFile(ConfigFile):
    def __init__(self):
        super().__init__(
            os.path.join(BRIDGE_CONFIG_DIR, "config.toml"),
            defaults={
                "MQTT": {
                    "server": "192.168.6.1",
                    "port": 1883,
                },
                "MQTT_TLS": {
                    "use_tls": False,
                    "ca_certs": None,
                    "certfile": None,
                    "keyfile": None,
                    "cert_reqs": 2,
                },
            },
        )

    def load_or_create_defaults(self, allow_empty: bool = False):  # type: ignore[override]
        super().load_or_create_defaults(allow_empty=allow_empty)
        try:
            cfg = BridgeConfig(**self.data)
            self.data = cfg.model_dump()
        except Exception:
            self.create_defaults()
            self.save()


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.INFO)
    boot = BridgeConfigFile()
    boot.load_or_create_defaults()
    boot.save()
    print(boot.data)
