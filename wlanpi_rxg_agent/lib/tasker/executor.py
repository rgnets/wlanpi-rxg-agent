import logging

import lib.agent_actions.domain as actions_domain
from busses import message_bus, command_bus
from core_client import CoreClient


class Executor():

    def __init__(self
                 ):
        self.core_client = CoreClient()


class PingExecutor(Executor):

    def __init__(self, ping_target:actions_domain.Data.PingTarget):
        super().__init__()

        self.ident_name = f"{self.__class__}:{ping_target.interface}:{ping_target.host}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")
        self.ping_target = ping_target
        pass

    def execute(self):
        # Check if wifi is correct

        # TODO: Errors when no destination host are found are resolved in a newer version of the JC library. To fix this, core will need to include the new version instead of using the system version.
        res = self.core_client.execute_request('post', 'api/v1/utils/ping', data ={
                "host": self.ping_target.host,
                "count": self.ping_target.count,
                "interval": self.ping_target.interval,
                "interface": self.ping_target.interface,
        })
        self.ping_batch_complete(result=res.json())


    def ping_batch_complete(self, result):
        if "message" in result:
            self.logger.warning(f"Something went wrong running ping: {result}")
            message_bus.handle(actions_domain.Messages.PingBatchFailure(id=self.ping_target.id, result=result))
        else:
            message_bus.handle(actions_domain.Messages.PingBatchComplete(id=self.ping_target.id, result=result))




if __name__ == "__main__":
    pt = actions_domain.Data.PingTarget(id=1, host='8.8.8.8', count=5, interval=0.2, timeout=10, interface='eth0')
    pe = PingExecutor(ping_target=pt)

    pe.execute()