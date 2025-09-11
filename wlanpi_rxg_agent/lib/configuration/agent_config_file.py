import os

from wlanpi_rxg_agent.lib.configuration.config_file import ConfigFile
from wlanpi_rxg_agent.lib.configuration.schemas import AgentConfig

AGENT_CONFIG_DIR = "/etc/wlanpi-rxg-agent"


class AgentConfigFile(ConfigFile):
    def __init__(self):
        super().__init__(
            os.path.join(AGENT_CONFIG_DIR, "config.toml"),
            defaults={
                "General": {
                    "override_rxg": "",
                    "fallback_rxg": "",
                }
            },
        )

    def load_or_create_defaults(self, allow_empty: bool = False):  # type: ignore[override]
        super().load_or_create_defaults(allow_empty=allow_empty)
        # Validate and normalize with schema; fall back to defaults on error
        try:
            cfg = AgentConfig(**self.data)
            self.data = cfg.model_dump()
        except Exception:
            # Recreate defaults if invalid
            self.create_defaults()
            self.save()


if __name__ == "__main__":
    boot = AgentConfigFile()
    boot.load()
    print(boot.data)
