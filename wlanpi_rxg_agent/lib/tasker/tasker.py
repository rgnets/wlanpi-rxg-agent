import logging
import asyncio
from typing import TypeVar, Generic

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel, Field, ConfigDict

from wlanpi_rxg_agent.busses import message_bus, command_bus
from wlanpi_rxg_agent.lib.tasker.executor import PingExecutor
from wlanpi_rxg_agent.lib.tasker.repeating_task import RepeatingTask
from wlanpi_rxg_agent.lib.wifi_control import domain as wifi_domain
from wlanpi_rxg_agent.lib.agent_actions import domain as actions_domain
import wlanpi_rxg_agent.lib.domain as agent_domain

TaskDefDataType = TypeVar('TaskDefDataType')

class TaskDefinition(BaseModel, Generic[TaskDefDataType]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = Field()
    definition: TaskDefDataType = Field()
    task_obj: RepeatingTask = Field()

class Tasker:

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.__class__}")

        # self.active_tasks: list = []

        self.loop = asyncio.get_event_loop()
        self.scheduler = AsyncIOScheduler(loop=self.loop)
        self.scheduler.start()


        self.scheduled_ping_targets: dict[str, TaskDefinition[actions_domain.Data.PingTarget]] = {}
        self.scheduled_traceroutes: dict[str, TaskDefinition[actions_domain.Data.Traceroute]] = {}
        self.scheduled_speed_tests: dict[str, TaskDefinition[actions_domain.Data.SpeedTest]] = {}



        # Event/Command Bus
        self.logger.debug("Setting up listeners")
        self.command_handler_pairs = (
            # (wifi_domain.Commands.GetOrCreateInterface, lambda event: self.get_or_create_interface(event.if_name)),
            (actions_domain.Commands.ConfigurePingTargets, lambda event: self.configure_ping_targets(event)),
            (agent_domain.Messages.ShutdownStarted, self.shutdown),
        )
        self.setup_listeners()

    def setup_listeners(self):
        # TODO: Surely we can implement this as some sort of decorator function?
        for command, handler in self.command_handler_pairs:
            command_bus.add_handler(command, handler)

    def teardown_listeners(self):
        # TODO: Surely we can implement this as some sort of decorator function?
        for command, handler in self.command_handler_pairs:
            command_bus.remove_handler(command)


    def shutdown(self):
        self.logger.info(f"Shutting down {__name__}")
        self.scheduler.shutdown()
        self.teardown_listeners()
        self.logger.info(f"{__name__} shutdown complete.")

    def __del__(self):
        self.shutdown()



    def configure_ping_targets(self, event: actions_domain.Commands.ConfigurePingTargets):
        # TODO: Implement this function to actually set the ping targets.

        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            if composite_id in self.scheduled_ping_targets:
                existing_task_def: TaskDefinition = self.scheduled_ping_targets[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug("Task already exists and matches target configuration. Skipping...")
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet!")
                pass
            else:
                new_task = RepeatingTask(
                    self.scheduler,
                    "PingTarget",
                    identifier=composite_id,
                    task_executor= lambda : PingExecutor(ping_target=target).execute(),
                    interval=60 #target.interval #Currently, interval is handled by the ping task itself.
                )

                self.scheduled_ping_targets[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task, definition=target)





