import asyncio
import inspect
import logging
from datetime import datetime, timedelta
from typing import Callable, Coroutine, Optional, Union

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Useful bits at https://coderslegacy.com/python-apscheduler-asyncioscheduler/


class OneShotTask:
    """
    Contains all the logical concepts for scheduling and executing an arbitrary repeating task
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        type: str,
        identifier: str,
        task_executor: Callable,
        start_date: Optional[datetime] = None,
        on_complete: Optional[Callable] = None,
    ):
        self.type = type
        self.identifier = identifier
        self.scheduler = scheduler
        self.ident_name = f"{self.__class__.__name__}:{self.type}:{self.identifier}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")

        self.start_date = start_date or datetime.now()
        self.task_executor = task_executor
        self.on_complete = on_complete

        self.job = self.scheduler.add_job(
            self.run_once,
            "date",
            name=self.ident_name,
            next_run_time=self.start_date,
            misfire_grace_time=120,
        )

    def end_task(self):
        try:
            self.job.remove()
        except JobLookupError:
            self.logger.warning(
                f"Error looking up job while ending task {self.identifier}. It was probably already removed."
            )
        if self.on_complete is not None:
            self.on_complete()
        # self.logger.info(f"Task ended: {self.identifier}")

    # Technically, jobs can be modified in place. Currently not doing that.

    async def run_once(self):
        try:
            res = self.task_executor()
            if isinstance(res, asyncio.Task):
                res = await res
            if inspect.isawaitable(res):
                res = await res
            self.logger.debug(f"Task complete: {res}")
        except Exception as e:
            # Don't allow any exceptions beyond here, as they would break the scheduler
            self.logger.exception("Error in task execution")
        finally:
            self.logger.info(
                f'One-shot complete for "{self.identifier}". Removing job and calling on_complete callbacks.'
            )
            self.end_task()
