import logging
import asyncio
from typing import TypeVar, Generic, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel, Field, ConfigDict

from busses import message_bus, command_bus
from lib.tasker.executor import PingExecutor, TraceRouteExecutor, Iperf3Executor
from lib.tasker.one_shot_task import OneShotTask
from lib.tasker.repeating_task import RepeatingTask
from lib.wifi_control import domain as wifi_domain
from lib.agent_actions import domain as actions_domain
import lib.domain as agent_domain

TaskDefDataType = TypeVar('TaskDefDataType')

class TaskDefinition(BaseModel, Generic[TaskDefDataType]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = Field()
    definition: TaskDefDataType = Field()
    task_obj: Union[RepeatingTask, OneShotTask] = Field()

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
            (actions_domain.Commands.ConfigureSpeedTests, lambda event: self.configure_speed_tests(event)),
            (actions_domain.Commands.ConfigureTraceroutes, lambda event: self.configure_traceroutes(event)),
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

            def create_new_task():
                new_task = RepeatingTask(
                    self.scheduler,
                    "PingTarget",
                    identifier=composite_id,
                    task_executor=lambda: PingExecutor(ping_target=target).execute(),
                    interval= target.period
                )

                self.scheduled_ping_targets[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                           definition=target)

            if composite_id in self.scheduled_ping_targets:
                existing_task_def: TaskDefinition = self.scheduled_ping_targets[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug("Task already exists and matches target configuration. Skipping...")
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet!")

                    # Cancel/stop the task
                    existing_task = self.scheduled_ping_targets[composite_id]
                    existing_task.task_obj.end_task()

                    # Create new task to replace it with
                    create_new_task()

                pass
            else:
                create_new_task()


    def configure_traceroutes(self, event: actions_domain.Commands.ConfigureTraceroutes):

        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            def create_new_task():
                new_task = RepeatingTask(
                    self.scheduler,
                    "TraceRoute",
                    identifier=composite_id,
                    task_executor=lambda: TraceRouteExecutor(traceroute_def=target).execute(),
                    interval=target.period
                )

                self.scheduled_traceroutes[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                           definition=target)

            if composite_id in self.scheduled_traceroutes:
                existing_task_def: TaskDefinition = self.scheduled_traceroutes[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug("Task already exists and matches target configuration. Skipping...")
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet!")

                    # Cancel/stop the task
                    existing_task = self.scheduled_traceroutes[composite_id]
                    existing_task.task_obj.end_task()

                    # Create new task to replace it with
                    create_new_task()

                pass
            else:
                create_new_task()


    def configure_speed_tests(self, event: actions_domain.Commands.ConfigureSpeedTests):

        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            def create_new_task():

                test_def = actions_domain.Data.Iperf3Test(**target.model_dump())

                if target.period:
                    new_task = RepeatingTask(
                        self.scheduler,
                        "TraceRoute",
                        identifier=composite_id,
                        task_executor=lambda: Iperf3Executor(iperf_def=test_def).execute(),
                        start_date=target.start_date,
                        interval=target.period
                    )
                else:
                    new_task = OneShotTask(
                        self.scheduler,
                        "Iperf3Test",
                        identifier=composite_id,
                        task_executor=lambda: Iperf3Executor(iperf_def=test_def).execute(),
                        start_date= target.start_date,
                        on_complete= lambda _ : self.scheduled_ping_targets.pop(composite_id)
                    )
                self.scheduled_ping_targets[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                           definition=target)

            if composite_id in self.scheduled_ping_targets:
                existing_task_def: TaskDefinition = self.scheduled_ping_targets[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug("Task already exists and matches target configuration. Skipping...")
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet!")

                    # Cancel/stop the task
                    existing_task = self.scheduled_ping_targets[composite_id]
                    existing_task.task_obj.end_task()

                    # Create new task to replace it with
                    create_new_task()

                pass
            else:
                create_new_task()





