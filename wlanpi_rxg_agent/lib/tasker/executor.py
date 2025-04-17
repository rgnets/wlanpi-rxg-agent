import logging
from typing import Type

import lib.agent_actions.domain as actions_domain
from busses import message_bus, command_bus
from core_client import CoreClient
from abc import ABC, abstractmethod


class Executor(ABC):

    def __init__(self
                 ):
        self.core_client = CoreClient()

        @abstractmethod
        def execute():
            pass

        @abstractmethod
        def execution_complete(self, result):
            pass


class PingExecutor(Executor):

    def __init__(self, ping_target:actions_domain.Data.PingTarget):
        super().__init__()

        self.ident_name = f"{self.__class__}:{ping_target.interface}:{ping_target.host}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")
        self.exec_def = ping_target

    def execute(self):
        # Check if wifi is correct

        # TODO: Errors when no destination host are found are resolved in a newer version of the JC library. To fix this, core will need to include the new version instead of using the system version.
        res = self.core_client.execute_request('post', 'api/v1/utils/ping', data ={

            **{x: y for x, y in self.exec_def.model_dump().items() if x not in ['id']}
                # "host": self.exec_def.host,
                # "count": self.exec_def.count,
                # "interval": self.exec_def.interval,
                # "interface": self.exec_def.interface,
        })
        self.execution_complete(message_model=actions_domain.Messages.PingBatchComplete, result=res.json())

    def execution_complete(self, message_model: Type[actions_domain.Messages.ExecutorCompleteMessage], result):
        if "message" in result:
            self.logger.warning(f"Something went wrong executor: {result}")
            message_bus.handle(message_model(id=self.exec_def.id, error=str(result)))
        else:
            message_bus.handle(message_model(id=self.exec_def.id, result=result))


class TraceRouteExecutor(Executor):

    def __init__(self, traceroute_def:actions_domain.Data.Traceroute):
        super().__init__()

        self.ident_name = f"{self.__class__}:{traceroute_def.interface}:{traceroute_def.host}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")
        self.exec_def = traceroute_def

    def execute(self):
        # Check if wifi is correct

        # TODO: Errors when no destination host are found are resolved in a newer version of the JC library. To fix this, core will need to include the new version instead of using the system version.
        res = self.core_client.execute_request('post', 'api/v1/utils/traceroute', data ={
            **{x: y for x, y in self.exec_def.model_dump().items() if x not in ['id']}
                # "host": self.exec_def.host,
                # "interface": self.exec_def.interface,
                # "queries": self.exec_def.queries,
                #
                #
                # # "count": self.traceroute_def.count,
                # # "interval": self.traceroute_def.interval,
        })
        self.execution_complete(message_model=actions_domain.Messages.TracerouteComplete, result=res.json())

    def execution_complete(self, message_model: Type[actions_domain.Messages.ExecutorCompleteMessage], result):
        if "message" in result:
            self.logger.warning(f"Something went wrong executor: {result}")
            message_bus.handle(message_model(id=self.exec_def.id, error=str(result), result=result))
        else:
            message_bus.handle(message_model(id=self.exec_def.id, result=result))


class Iperf2Executor(Executor):

    def __init__(self, iperf_def:actions_domain.Data.Iperf2Test):
        super().__init__()

        self.ident_name = f"{self.__class__}:{iperf_def.interface}:{iperf_def.host}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")
        self.exec_def = iperf_def

    def execute(self):
        res = self.core_client.execute_request('post', 'api/v1/utils/iperf2/client', data ={
                **{x:y for x,y in self.exec_def.model_dump().items() if x not in ['id']}
        })
        self.execution_complete(message_model=actions_domain.Messages.Iperf2Complete, result=res.json())

    def execution_complete(self, message_model: Type[actions_domain.Messages.ExecutorCompleteMessage],  result):
        if "message" in result:
            self.logger.warning(f"Something went wrong executor: {result}")
            message_bus.handle(message_model(id=self.exec_def.id, error=str(result), result=result))
        else:
            message_bus.handle(message_model(id=self.exec_def.id, result=result))



class Iperf3Executor(Executor):

    def __init__(self, iperf_def:actions_domain.Data.Iperf3Test):
        super().__init__()

        self.ident_name = f"{self.__class__}:{iperf_def.interface}:{iperf_def.host}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")
        self.exec_def = iperf_def

    def execute(self):
        res = self.core_client.execute_request('post', 'api/v1/utils/iperf3/client', data ={
                **{x:y for x,y in self.exec_def.model_dump().items() if x not in ['id']}
        })
        self.execution_complete(message_model=actions_domain.Messages.Iperf3Complete, result=res.json())

    def execution_complete(self, message_model: Type[actions_domain.Messages.ExecutorCompleteMessage],  result):
        if "message" in result:
            self.logger.warning(f"Something went wrong executor: {result}")
            message_bus.handle(message_model(id=self.exec_def.id, error=str(result), result=result))
        else:
            message_bus.handle(message_model(id=self.exec_def.id, result=result))






if __name__ == "__main__":
    # pt = actions_domain.Data.PingTarget(id=1, host='8.8.8.8', count=5, interval=0.2, timeout=10, interface='eth0')
    # pe = PingExecutor(ping_target=pt)
    # pe.execute()
    #
    #
    # tr = actions_domain.Data.Traceroute(id=1, host='emkode.io', period=10, interface='eth0')
    # tre = TraceRouteExecutor(traceroute_def=tr)
    # tre.execute()
    #
    #
    # iperf = actions_domain.Data.Iperf2Test(id=1, host='rxg.ketchel.xyz', port=5001, time=5, interface='eth0')
    # iperfe = Iperf2Executor(iperf_def=iperf)
    # iperfe.execute()

    iperf = actions_domain.Data.Iperf3Test(id=1, host='rxg.ketchel.xyz', port=5201, time=5, interface='eth0')
    iperfe = Iperf3Executor(iperf_def=iperf)
    iperfe.execute()
