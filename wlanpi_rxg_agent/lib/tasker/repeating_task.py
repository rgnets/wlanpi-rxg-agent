import inspect
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Coroutine, Callable, Union, Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler


# Useful bits at https://coderslegacy.com/python-apscheduler-asyncioscheduler/

class RepeatingTask:
    '''
    Contains all the logical concepts for scheduling and executing an arbitrary repeating task
    '''

    def __init__(self, scheduler: AsyncIOScheduler, type: str, identifier: str, task_executor: Callable, interval: float,
                 start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
        self.type = type
        self.identifier = identifier
        self.scheduler = scheduler
        self.ident_name = f"{self.__class__}:{self.type}:{self.identifier}"
        self.logger = logging.getLogger(self.ident_name)
        # self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {self.ident_name}")

        self.start_date = start_date
        self.end_date = end_date
        self.interval = interval

        self.task_executor = task_executor

        self.job = self.scheduler.add_job(self.run_once,
                                          'interval',
                                          name=self.ident_name,
                                          seconds=self.interval,
                                          start_date=self.start_date,
                                          end_date=self.end_date,
                                          # start_date='2023-06-21 10:00:00',
                                          # end_date='2023-06-21 11:00:00'
                                          misfire_grace_time=int(self.interval/2),
                                          )

    def end_task(self):
        try:
            self.job.remove()
        except JobLookupError:
            self.logger.warning(f"Error looking up job while ending task {self.identifier}. It was probably already removed.")
        self.logger.info(f"Task ended: {self.identifier}")

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


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    scheduler = AsyncIOScheduler(loop=loop)

    # async def main():

    async def go():
        print("Starting scheduler")

        scheduler.start()
        def the_task():
            print("Working hard!")
            logger.info("Working hard!")

        print("Task init")
        rt = RepeatingTask(
            scheduler=scheduler,
            type="TestTask",
            identifier='Number1',
            task_executor=the_task,
            interval=10,
            start_date=datetime.now() - timedelta(0,15)
        )

        print(f"Task: {rt}")
        # asyncio.get_event_loop().run_forever()

    try:
        loop.create_task(go())
        loop.run_forever()

        # asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("Ignoring keyboard interrupt")
        pass
    finally:
        scheduler.shutdown()
    # main()
    # asyncio.run(main())