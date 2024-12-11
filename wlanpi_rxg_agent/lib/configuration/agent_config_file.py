import os

from lib.configuration.config_file import ConfigFile

AGENT_CONFIG_DIR = "/etc/wlanpi-rxg-agent"


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



if __name__ == "__main__":
    boot = AgentConfigFile()
    boot.load()
    print(boot.data)