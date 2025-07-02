import asyncio
import logging
import time
from typing import Optional
import threading
from lib.sip_control.custom_baresipy import CustomBaresipy
from lib.sip_control.mdk_baresip import MdkBareSIP



class SipTestBaresip:

    def __init__(self,
                 gateway:str,
                 user: str,
                 password: str,
                 # callee: str,
                 # post_connect: Optional[str] = None,
                 # call_timeout: Optional[int] = None,
                 extra_login_args: Optional[str] = None,
                 debug: bool=False
                 ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self._gateway = gateway
        self._user = user
        self._password = password
        self._debug = debug
        # self.callee = callee
        # self.post_connect = post_connect
        self._extra_login_args = extra_login_args
        # self.baresip = MdkBareSIP(user=self._user, pwd=self._password, gateway=self._gateway, debug=self._debug)
        self.logger.info("SipTestBaresip initialized")



    async def execute(self, callee: str, post_connect: Optional[str] = None, call_timeout: Optional[int] = None):
        async with MdkBareSIP(gateway=self._gateway, user=self._user, pwd=self._password, debug=self._debug, extra_login_args=self._extra_login_args) as bs:
            self.logger.info(f"Executing test against {callee}")

            loop = asyncio.get_running_loop()
            in_progress = loop.create_future()

            @bs.ee.listens_to(str(bs.Events.SUMMARY))
            def handle_rtcp_summary(summary: dict, *_, **__):
                self.logger.info(f"Received RTCP summary: {summary}")

            @bs.ee.listens_to(str(bs.Events.ESTABLISHED))
            def call_established(bs_instance: MdkBareSIP, *_, **__):
                self.logger.info("call established")
                if post_connect:
                    bs_instance.send_dtmf(post_connect)
                bs_instance.speak("Your mom's a hoe.")
                time.sleep(0.5)
                bs_instance.hang()
                if not (in_progress.done() or in_progress.cancelled()): in_progress.set_result(True)

            @bs.ee.listens_to(str(bs.Events.SESSION_CLOSED))
            def handle_call_ended_abnormally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended abnormally")
                # self.logger.debug((in_progress.done(), in_progress.cancelled()))
                if not (in_progress.done() or in_progress.cancelled()): in_progress.set_result(False)

            @bs.ee.listens_to(str(bs.Events.TERMINATED))
            def handle_call_ended_normally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended normally")
                # print((in_progress.done(), in_progress.cancelled()))
                if not (in_progress.done() or in_progress.cancelled()): in_progress.set_result(True)

            bs.call(callee)

            self.logger.info("Waiting for call to end")
            try:
                if call_timeout:
                    await asyncio.wait_for(in_progress, timeout=call_timeout)
                else:
                    await in_progress
                self.logger.info("Test completed")
            except asyncio.TimeoutError:
                self.logger.warning(f"Call timed out after {call_timeout} seconds. Forcibly hanging up.")
                bs.hang()



if __name__ == "__main__":

    async def main():
        sip_test = SipTestBaresip(gateway="192.168.7.15", user="user", password="password", debug=True)
        await sip_test.execute(callee="1234", post_connect="1234", call_timeout=10)
        print("done!")


    asyncio.get_event_loop().run_until_complete(main())

