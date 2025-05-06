import logging
import asyncio
from datetime import datetime, timedelta
from typing import TypeVar, Generic, Union, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel, Field, ConfigDict

from busses import message_bus, command_bus
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
        self.scheduler = AsyncIOScheduler(loop=self.loop, misfire_grace_time=30)
        self.scheduler.start()


        self.scheduled_ping_targets: dict[str, TaskDefinition[actions_domain.Data.PingTarget]] = {}
        self.scheduled_traceroutes: dict[str, TaskDefinition[actions_domain.Data.Traceroute]] = {}
        self.scheduled_speed_tests: dict[str, TaskDefinition[actions_domain.Data.SpeedTest]] = {}
        self.misc_tasks: dict[str, TaskDefinition[Any]] = {}


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

        self.configure_fixed_tasks()

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

    def debug_tick_task(self):
        print('Tick! The time is: %s' % datetime.now())

    def debug_dump_task(self):
        self.logger.debug(f"Scheduled PingTargets: {self.scheduled_ping_targets.items()}")
        self.logger.debug(f"Scheduled TraceRoutes: {self.scheduled_traceroutes.items()}")
        self.logger.debug(f"Scheduled SpeedTests: {self.scheduled_speed_tests.items()}")
        self.logger.debug(f"Scheduled misc: {self.misc_tasks.items()}")
        self.logger.debug(f"Raw Scheduler jobs: {self.scheduler.get_jobs()}")

    def configure_fixed_tasks(self):
        # Configures fixed tasks that always run while the tasker is running.
        self.logger.info("Configuring fixed tasks")
        fixed_task_prefix = "ft_"
        fixed_tasks = [
            ["dig_eth0", "DigTest", 60, lambda: command_bus.handle(actions_domain.Commands.Dig( host='google.com', interface='eth0'))],
            ["dhcp_eth0", "DhcpTest", 60, lambda: command_bus.handle(actions_domain.Commands.DhcpTest( interface='eth0', timeout=10))],
        ]
        
        for task_ident, task_type, task_period, task_func in fixed_tasks:
            task_ident = fixed_task_prefix + task_ident
            self.logger.info(f"Configuring {task_ident}")
            new_task = RepeatingTask(
                self.scheduler,
                task_type,
                identifier=task_ident,
                task_executor=task_func,
                interval=task_period,
                start_date=datetime.now() + timedelta(seconds=10)
            )
            self.misc_tasks[task_ident] = TaskDefinition(id=task_ident, task_obj=new_task,
                                                                           definition=None)
        # self.misc_tasks['debug_tick'] = TaskDefinition(id="DebugTickTask",definition={}, task_obj=Re)
        # self.scheduler.add_job(self.debug_tick_task, 'interval', seconds=2)
        self.scheduler.add_job(self.debug_dump_task, 'interval', seconds=10)

    def configure_ping_targets(self, event: actions_domain.Commands.ConfigurePingTargets):
        # Configure ping targets based on agent config payload, delivered to this as an event.
        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"
            if composite_id in self.scheduled_ping_targets:
                existing_task_def: TaskDefinition = self.scheduled_ping_targets[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug(f"Task \"{composite_id}\" (from event {event.__class__}) already exists and matches target configuration. Skipping...")
                    continue
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet! Replacing task.")

                    # Cancel/stop the task
                    existing_task = self.scheduled_ping_targets[composite_id]
                    existing_task.task_obj.end_task()


            async def execute(exec_def: actions_domain.Data.PingTarget = target):
                self.logger.info(f"Executing PingTarget: {target.model_dump(mode='json')}")
                ping_command = actions_domain.Commands.Ping(
                    host=exec_def.host,
                    count=exec_def.count,
                    interval=exec_def.interval,
                    # TTL isn't present on ping target
                    # TODO: Implement timeout logic
                    interface=exec_def.interface,
                )
                # TODO: Do something better than just triggering DHCP and DNS tests here.
                command_bus.handle(actions_domain.Commands.DhcpTest(interface=exec_def.interface, timeout=10))
                command_bus.handle(actions_domain.Commands.Dig(host=exec_def.host, interface=exec_def.interface))

                res = await command_bus.handle(ping_command)
                self.logger.debug(f"Execution complete: {res}")
                message_bus.handle(actions_domain.Messages.PingComplete(id=exec_def.id, result=res, request=ping_command))

            new_task = RepeatingTask(
                self.scheduler,
                "PingTarget",
                identifier=composite_id,
                task_executor=execute,
                interval=target.period
            )

            self.scheduled_ping_targets[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                       definition=target)

    def configure_traceroutes(self, event: actions_domain.Commands.ConfigureTraceroutes):
        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            if composite_id in self.scheduled_traceroutes:
                existing_task_def: TaskDefinition = self.scheduled_traceroutes[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug(f"Task \"{composite_id}\" (from event {event.__class__}) already exists and matches target configuration. Skipping...")
                    continue
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet! Replacing task.")

                    # Cancel/stop the task
                    existing_task = self.scheduled_traceroutes[composite_id]
                    existing_task.task_obj.end_task()

                    # Create new task to replace it with

            async def execute(exec_def: actions_domain.Data.Traceroute = target):
                self.logger.info(f"Executing TraceRoute: {target.model_dump(mode='json')}")
                tr_command = actions_domain.Commands.Traceroute(
                    host=exec_def.host,
                    interface=exec_def.interface,
                    #bypass_routing is unused
                    queries=exec_def.queries
                )
                res : actions_domain.Messages.TracerouteResponse = await command_bus.handle(tr_command)
                self.logger.debug(f"Execution complete: {res}")
                message_bus.handle(actions_domain.Messages.TracerouteComplete(id=exec_def.id, result=res, request=tr_command))

            new_task = RepeatingTask(
                self.scheduler,
                "TraceRoute",
                identifier=composite_id,
                task_executor=execute,
                interval=target.period
            )
            self.scheduled_traceroutes[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                      definition=target)


    def configure_speed_tests(self, event: actions_domain.Commands.ConfigureSpeedTests):
        self.logger.warning("Speed test scheduling is temporarily disabled in code due to how it's handled on the rxg.")
        return
        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            if composite_id in self.scheduled_speed_tests:
                existing_task_def: TaskDefinition = self.scheduled_speed_tests[composite_id]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug(f"Task \"{composite_id}\" (from event {event.__class__}) already exists and matches target configuration. Skipping...")
                    continue
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning("Task modification not supported yet! Replacing task.")

                    # Cancel/stop the task
                    existing_task = self.scheduled_speed_tests[composite_id]
                    existing_task.task_obj.end_task()

            test_def = actions_domain.Data.Iperf3Test(**target.model_dump())

            async def execute(exec_def: actions_domain.Data.Iperf3Test = test_def):
                self.logger.info(f"Executing Iperf3Test: {target.model_dump(mode='json')}")
                iperf_cmd = actions_domain.Commands.Iperf3(**{x:y for x,y in exec_def.model_dump().items() if x not in ['id']})
                res = await command_bus.handle(iperf_cmd)
                self.logger.debug(f"Execution complete: {res}")
                message_bus.handle(actions_domain.Messages.Iperf3Complete(id=exec_def.id, result=res, request=iperf_cmd))

            if target.period:
                new_task = RepeatingTask(
                    self.scheduler,
                    "TraceRoute",
                    identifier=composite_id,
                    task_executor=execute,
                    start_date=target.start_date,
                    interval=target.period
                )

                self.scheduled_speed_tests[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                          definition=target)
            else:
                self.logger.debug("Speed test with no period found. This is probably a manual one. Ignoring.")

                # def on_complete(composite_id):
                #     logging.debug(
                #         f"Dropping {composite_id} from scheduled_speed_tests. Current keys: {self.scheduled_speed_tests.keys()}")
                #     self.scheduled_speed_tests.pop(composite_id)
                #
                # new_task = OneShotTask(
                #     self.scheduler,
                #     "Iperf3Test",
                #     identifier=composite_id,
                #     task_executor=lambda: execute(test_def),
                #     start_date=target.start_date,
                #     on_complete=lambda: on_complete(composite_id)
                # )
            # self.scheduled_speed_tests[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
            #                                                           definition=target)


    def one_off_speed_test(self, target):

        composite_id = f"oo_{target.id}:{target.interface}"

        if composite_id in self.scheduled_speed_tests:
            existing_task_def: TaskDefinition = self.scheduled_speed_tests[composite_id]

            if existing_task_def.definition == target:
                # Nothing needed, tasks should match
                self.logger.debug(
                    f"Task \"{composite_id}\" (from event {event.__class__}) already exists and matches target configuration. Skipping...")
                return
            else:
                # Tasks exists but the configuration does not match. Update it.
                self.logger.warning("Task modification not supported yet! Replacing task.")

                # Cancel/stop the task
                existing_task = self.scheduled_speed_tests[composite_id]
                existing_task.task_obj.end_task()

        test_def = actions_domain.Data.Iperf3Test(**target.model_dump())

        async def execute(exec_def: actions_domain.Data.Iperf3Test = test_def):
            self.logger.info(f"Executing Iperf3Test: {target.model_dump(mode='json')}")
            iperf_cmd = actions_domain.Commands.Iperf3(
                **{x: y for x, y in exec_def.model_dump().items() if x not in ['id']})
            res = await command_bus.handle(iperf_cmd)
            self.logger.debug(f"Execution complete: {res}")
            message_bus.handle(
                actions_domain.Messages.Iperf3Complete(id=exec_def.id, result=res, request=iperf_cmd))

        if target.period:
            new_task = RepeatingTask(
                self.scheduler,
                "TraceRoute",
                identifier=composite_id,
                task_executor=execute,
                start_date=target.start_date,
                interval=target.period
            )

            self.scheduled_speed_tests[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
                                                                      definition=target)
        else:
            self.logger.debug("Speed test with no period found. This is probably a manual one. Ignoring.")

            # def on_complete(composite_id):
            #     logging.debug(
            #         f"Dropping {composite_id} from scheduled_speed_tests. Current keys: {self.scheduled_speed_tests.keys()}")
            #     self.scheduled_speed_tests.pop(composite_id)
            #
            # new_task = OneShotTask(
            #     self.scheduler,
            #     "Iperf3Test",
            #     identifier=composite_id,
            #     task_executor=lambda: execute(test_def),
            #     start_date=target.start_date,
            #     on_complete=lambda: on_complete(composite_id)
            # )
        # self.scheduled_speed_tests[composite_id] = TaskDefinition(id=composite_id, task_obj=new_task,
        #                                                           definition=target)



