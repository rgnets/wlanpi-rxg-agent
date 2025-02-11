import logging

import utils
from busses import message_bus, command_bus
import lib.domain as agent_domain
import lib.rxg_supplicant.domain as supplicant_domain
import lib.agent_actions.domain as actions_domain
from lib.configuration.bootloader_config_file import BootloaderConfigFile


class AgentActions():

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.bootloader_config = BootloaderConfigFile()
        self.setup_listeners()

    def setup_listeners(self):
        # TODO: Surely we can implement this as some sort of decorator function?
        pairs = (
            (actions_domain.Commands.SetRxgs, self.set_rxgs),
            (actions_domain.Commands.SetCredentials, self.set_password),
            (actions_domain.Commands.Reboot, self.reboot),
        )

        for command, handler in pairs:
            command_bus.add_handler(command, handler)

    async def reboot(self):
        self.logger.info(f"Rebooting")
        return utils.run_command("reboot", raise_on_fail=False)

    async def set_rxgs(self, data:actions_domain.Commands.SetRxgs):
        self.bootloader_config.load()

        if data.override is not None:
            self.logger.info(f"Setting override_rxg: {data.override}")
            self.bootloader_config.data["boot_server_override"] = data.override

        if data.fallback is not None:
            self.logger.info(f"Setting fallback_rxg: {data.fallback}")
            self.bootloader_config.data["boot_server_fallback"] = data.fallback["value"]
        self.bootloader_config.save()
        message_bus.handle(agent_domain.Messages.AgentConfigUpdate(
            override_rxg=data.override,
            fallback_rxg=data.fallback
        ))
        # if self.agent_reconfig_callback is not None:
        #     await self.agent_reconfig_callback({"override_rxg": value})
        return self.bootloader_config.data

    async def set_password(self, payload):
        self.logger.info(f"Setting new password.")
        return await utils.run_command_async("chpasswd", input=f"wlanpi:{payload['value']}")

