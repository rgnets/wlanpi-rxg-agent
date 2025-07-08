import asyncio
import functools
import logging
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar, Union, Callable

import lib.domain as agent_domain
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from busses import command_bus, message_bus
from lib.agent_actions import domain as actions_domain
from lib.tasker.one_shot_task import OneShotTask
from lib.tasker.repeating_task import RepeatingTask
from lib.wifi_control import domain as wifi_domain
from pydantic import BaseModel, ConfigDict, Field

TaskDefDataType = TypeVar("TaskDefDataType")


class TaskDefinition(BaseModel, Generic[TaskDefDataType]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = Field()
    definition: TaskDefDataType = Field()
    task_obj: Union[RepeatingTask, OneShotTask] = Field()


class Tasker:

    class ScheduledTasks:
        ping_targets: dict[
            str, TaskDefinition[actions_domain.Data.PingTarget]
        ] = {}
        traceroutes: dict[
            str, TaskDefinition[actions_domain.Data.Traceroute]
        ] = {}
        speed_tests: dict[
            str, TaskDefinition[actions_domain.Data.SpeedTest]
        ] = {}
        sip_tests: dict[
            str, TaskDefinition[actions_domain.Data.SipTest]
        ] = {}
        misc_tasks: dict[str, TaskDefinition[Any]] = {}

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.__class__}")

        # self.active_tasks: list = []

        self.loop = asyncio.get_event_loop()
        self.scheduler = AsyncIOScheduler(loop=self.loop, misfire_grace_time=30)
        self.scheduler.start()


        self.scheduled_tasks: Tasker.ScheduledTasks = Tasker.ScheduledTasks()

        # Event/Command Bus
        self.logger.debug("Setting up listeners")
        self.command_handler_pairs = (
            # (wifi_domain.Commands.GetOrCreateInterface, lambda event: self.get_or_create_interface(event.if_name)),
            (
                actions_domain.Commands.ConfigurePingTargets,
                lambda event: self.configured_ping_targets(event),
            ),
            (
                actions_domain.Commands.ConfigureSpeedTests,
                lambda event: self.configure_speed_tests(event),
            ),
            (
                actions_domain.Commands.ConfigureTraceroutes,
                lambda event: self.configured_traceroutes(event),
            ),
            (
                actions_domain.Commands.ConfigureSipTests,
                lambda event: self.configured_sip_tests(event),
            ),
            (agent_domain.Messages.ShutdownStarted, self.shutdown),
        )
        self.setup_listeners()

        self.configure_fixed_tasks()

    def setup_listeners(self):
        self.logger.info("Setting up listeners")
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
        print("Tick! The time is: %s" % datetime.now())

    def debug_dump_task(self):
        self.logger.debug(
            f"Scheduled PingTargets: {self.scheduled_tasks.ping_targets.items()}"
        )
        self.logger.debug(
            f"Scheduled TraceRoutes: {self.scheduled_tasks.traceroutes.items()}"
        )
        self.logger.debug(f"Scheduled SpeedTests: {self.scheduled_tasks.speed_tests.items()}")
        self.logger.debug(f"Scheduled SipTests: {self.scheduled_tasks.sip_tests.items()}")
        self.logger.debug(f"Scheduled misc: {self.scheduled_tasks.misc_tasks.items()}")
        self.logger.debug(f"Raw Scheduler jobs: {self.scheduler.get_jobs()}")

    def configure_fixed_tasks(self):
        # Configures fixed tasks that always run while the tasker is running.
        self.logger.info("Configuring fixed tasks")
        fixed_task_prefix = "ft_"
        fixed_tasks = [
            [
                "dig_eth0",
                "DigTest",
                60,
                lambda: command_bus.handle(
                    actions_domain.Commands.Dig(host="google.com", interface="eth0")
                ),
            ],
            [
                "dhcp_eth0",
                "DhcpTest",
                60,
                lambda: command_bus.handle(
                    actions_domain.Commands.DhcpTest(interface="eth0", timeout=10)
                ),
            ],
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
                start_date=datetime.now() + timedelta(seconds=10),
            )
            self.scheduled_tasks.misc_tasks[task_ident] = TaskDefinition(
                id=task_ident, task_obj=new_task, definition=None
            )
        # self.misc_tasks['debug_tick'] = TaskDefinition(id="DebugTickTask",definition={}, task_obj=Re)
        # self.scheduler.add_job(self.debug_tick_task, 'interval', seconds=2)
        self.scheduler.add_job(self.debug_dump_task, "interval", seconds=10)

    # This is a decorator function, so it doesn't follow the type rules quite how MyPy expects
    def configure_test(  # type: ignore
            task_type_name:str, task_schedule_name:str, event_type = actions_domain.Commands.ConfigureSipTests,
    ):
        def decorator_configure_test(func:Callable):
            @functools.wraps(func)
            def wrapper_configure_test(self, event: event_type):
                task_schedule = self.scheduled_tasks.__getattribute__(task_schedule_name)
                for target in event.targets:
                    composite_id = f"{target.id}:{target.interface}"

                    if composite_id in task_schedule:
                        existing_task_def: TaskDefinition = task_schedule[
                            composite_id
                        ]

                        if existing_task_def.definition == target:
                            # Nothing needed, tasks should match
                            self.logger.debug(
                                f'Task "{composite_id}" (from event {event.__class__}) already exists and matches target configuration. Skipping...'
                            )
                            continue
                        else:
                            # Tasks exists but the configuration does not match. Update it.
                            self.logger.warning(
                                "Task modification not supported yet! Replacing task."
                            )

                            # Cancel/stop the task
                            existing_task = task_schedule[composite_id]
                            existing_task.task_obj.end_task()

                            # Create new task to replace it with

                    # Accept decorated function as executor
                    def executor_function():
                        self.logger.info(
                            f"Executing {task_type_name}: {target.model_dump(mode='json')}"
                        )
                        return func(self, exec_def=target)

                    execute = executor_function

                    interval = target.period
                    if period_unit := getattr(target, 'period_unit', None):
                        if period_unit == 'seconds':
                            pass
                        elif period_unit == 'minutes':
                            interval = target.period * 60
                        elif period_unit == 'hours':
                            interval = target.period * 60 * 60
                        elif period_unit == 'days':
                            interval = target.period * 60 * 60 * 24
                        elif period_unit == 'weeks':
                            interval = target.period * 60 * 60 * 24 * 7
                        else:
                            self.logger.warning(f"Unknown period unit: {period_unit}")
                    new_task = RepeatingTask(
                        self.scheduler,
                        task_type_name,
                        identifier=composite_id,
                        task_executor=execute,
                        interval=interval,
                    )
                    task_schedule[composite_id] = TaskDefinition(
                        id=composite_id, task_obj=new_task, definition=target
                    )
            return wrapper_configure_test
        return decorator_configure_test

    @configure_test("SipTest", "sip_tests", event_type=actions_domain.Commands.ConfigureSipTests)
    async def configured_sip_tests(self, exec_def: actions_domain.Data.SipTest):
        self.logger.warning("I'm Not a real boy!!!")
        command = actions_domain.Commands.SipTest(
            **exec_def.model_dump(by_alias=True),
        )
        res = await command_bus.handle(command)
        self.logger.debug(f"Execution complete: {res}")
        # message_bus.handle(
        #     actions_domain.Messages.SipTestComplete(
        #         id=exec_def.id, result=res, request=command
        #     )
        # )

    @configure_test("PingTarget", "ping_targets", event_type=actions_domain.Commands.ConfigurePingTargets)
    async def configured_ping_targets (self, exec_def: actions_domain.Data.PingTarget):
        self.logger.warning("BRINGUS THE PINGUS!")
        ping_command = actions_domain.Commands.Ping(
            host=exec_def.host,
            count=exec_def.count,
            interval=exec_def.interval,
            # TTL isn't present on ping target
            # TODO: Implement timeout logic
            interface=exec_def.interface,
        )
        # TODO: Do something better than just triggering DHCP and DNS tests here.
        results = await asyncio.gather(
            command_bus.handle(
                actions_domain.Commands.DhcpTest(
                    interface=exec_def.interface, timeout=10
                )
            ),
            command_bus.handle(
                actions_domain.Commands.Dig(
                    host=exec_def.host, interface=exec_def.interface
                )
            ),
            command_bus.handle(ping_command)
        , return_exceptions=True)

        self.logger.debug(f"Execution ping, dig, and dhcp tests complete: {results}")

        message_bus.handle(
            actions_domain.Messages.PingComplete(
                id=exec_def.id, result=results[2], request=ping_command
            )
        )


    @configure_test("TraceRoute", "traceroutes", event_type=actions_domain.Commands.ConfigureTraceroutes)
    async def configured_traceroutes(
        self, exec_def: actions_domain.Data.Traceroute
    ):
        tr_command = actions_domain.Commands.Traceroute(
            host=exec_def.host,
            interface=exec_def.interface,
            # bypass_routing is unused
            queries=exec_def.queries,
        )
        res: actions_domain.Messages.TracerouteResponse = (
            await command_bus.handle(tr_command)
        )
        self.logger.debug(f"Execution complete: {res}")
        message_bus.handle(
            actions_domain.Messages.TracerouteComplete(
                id=exec_def.id, result=res, request=tr_command
            )
        )

    def configure_speed_tests(self, event: actions_domain.Commands.ConfigureSpeedTests):
        self.logger.warning(
            "Speed test scheduling is temporarily disabled in code due to how it's handled on the rxg."
        )
        return
        for target in event.targets:
            composite_id = f"{target.id}:{target.interface}"

            if composite_id in self.scheduled_speed_tests:
                existing_task_def: TaskDefinition = self.scheduled_speed_tests[
                    composite_id
                ]

                if existing_task_def.definition == target:
                    # Nothing needed, tasks should match
                    self.logger.debug(
                        f'Task "{composite_id}" (from event {event.__class__}) already exists and matches target configuration. Skipping...'
                    )
                    continue
                else:
                    # Tasks exists but the configuration does not match. Update it.
                    self.logger.warning(
                        "Task modification not supported yet! Replacing task."
                    )

                    # Cancel/stop the task
                    existing_task = self.scheduled_speed_tests[composite_id]
                    existing_task.task_obj.end_task()

            test_def = actions_domain.Data.Iperf3Test(**target.model_dump())

            async def execute(exec_def: actions_domain.Data.Iperf3Test = test_def):
                self.logger.info(
                    f"Executing Iperf3Test: {target.model_dump(mode='json')}"
                )
                iperf_cmd = actions_domain.Commands.Iperf3(
                    **{
                        x: y
                        for x, y in exec_def.model_dump().items()
                        if x not in ["id"]
                    }
                )
                res = await command_bus.handle(iperf_cmd)
                self.logger.debug(f"Execution complete: {res}")
                message_bus.handle(
                    actions_domain.Messages.Iperf3Complete(
                        id=exec_def.id, result=res, request=iperf_cmd
                    )
                )

            if target.period:
                new_task = RepeatingTask(
                    self.scheduler,
                    "TraceRoute",
                    identifier=composite_id,
                    task_executor=execute,
                    start_date=target.start_date,
                    interval=target.period,
                )

                self.scheduled_speed_tests[composite_id] = TaskDefinition(
                    id=composite_id, task_obj=new_task, definition=target
                )
            else:
                self.logger.debug(
                    "Speed test with no period found. This is probably a manual one. Ignoring."
                )

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
                    f'Task "{composite_id}" (from event {event.__class__}) already exists and matches target configuration. Skipping...'
                )
                return
            else:
                # Tasks exists but the configuration does not match. Update it.
                self.logger.warning(
                    "Task modification not supported yet! Replacing task."
                )

                # Cancel/stop the task
                existing_task = self.scheduled_speed_tests[composite_id]
                existing_task.task_obj.end_task()

        test_def = actions_domain.Data.Iperf3Test(**target.model_dump())

        async def execute(exec_def: actions_domain.Data.Iperf3Test = test_def):
            self.logger.info(f"Executing Iperf3Test: {target.model_dump(mode='json')}")
            iperf_cmd = actions_domain.Commands.Iperf3(
                **{x: y for x, y in exec_def.model_dump().items() if x not in ["id"]}
            )
            res = await command_bus.handle(iperf_cmd)
            self.logger.debug(f"Execution complete: {res}")
            message_bus.handle(
                actions_domain.Messages.Iperf3Complete(
                    id=exec_def.id, result=res, request=iperf_cmd
                )
            )

        if target.period:
            new_task = RepeatingTask(
                self.scheduler,
                "TraceRoute",
                identifier=composite_id,
                task_executor=execute,
                start_date=target.start_date,
                interval=target.period,
            )

            self.scheduled_speed_tests[composite_id] = TaskDefinition(
                id=composite_id, task_obj=new_task, definition=target
            )
        else:
            self.logger.debug(
                "Speed test with no period found. This is probably a manual one. Ignoring."
            )

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
