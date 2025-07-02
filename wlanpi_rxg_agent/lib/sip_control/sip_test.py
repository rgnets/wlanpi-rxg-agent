import asyncio
import logging
import time
from typing import Optional
import threading
from lib.sip_control.custom_baresipy import CustomBaresipy
from lib.sip_control.sip_control import SipInstance


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
        self.baresip = CustomBaresipy(user=self._user, pwd=self._password, gateway=self._gateway, block=False,
                                                debug=self._debug)
        self.logger.info("SipTestBaresip initialized")



    async def execute(self, callee: str, post_connect: Optional[str] = None, call_timeout: Optional[int] = None):
        self.logger.info(f"Executing test against {callee}")

        loop = asyncio.get_running_loop()

        in_progress = loop.create_future()

        def handle_rtcp_summary( summary: dict, *_, **__):
            self.logger.info(f"Received RTCP summary: {summary}")

        def handle_call_established(bs_instance:CustomBaresipy, *_, **__):
            if post_connect:
                bs_instance.send_dtmf(post_connect)
            bs_instance.speak("Your mom's a hoe.")
            time.sleep(0.5)
            bs_instance.hang()
            # in_progress.set_result(True)
            # self.baresip.quit()

        def handle_call_ended_abnormally(bs_instance:CustomBaresipy, *_, **__):
            self.logger.info("Call ended abnormally")
            self.logger.debug((in_progress.done(), in_progress.cancelled()))
            if not (in_progress.done() or in_progress.cancelled()):
                in_progress.set_result(False)

        def handle_call_ended_normally(bs_instance:CustomBaresipy, *_, **__):

            print(f"(call ended) Current thread ID: {threading.get_ident()}")
            self.logger.info("Call ended normally")
            self.logger.debug((in_progress.done(), in_progress.cancelled()))
            if not (in_progress.done() or in_progress.cancelled()):
                in_progress.set_result(True)

        self.baresip.em.on("rtcp_summary", handle_rtcp_summary)
        self.baresip.em.on("call_established", handle_call_established)
        self.baresip.em.on("session_closed", handle_call_ended_abnormally)
        self.baresip.em.on("call_terminated", handle_call_ended_normally)
        self.baresip.call(callee)

        # Dirty hack for now, don't keep this shit.
        # while self.baresip.running:
        #     time.sleep(0.5)
        self.logger.info("Waiting for call to end")

        print(f"(waiting) Current thread ID: {threading.get_ident()}")
        await in_progress
        self.logger.info("Test completed")
        # self.baresip.quit()


    async def __aenter__(self):
        self.logger.info("Entering async context")
        await self.baresip.async_wait_until_ready()
        self.logger.info("Baresip is ready")
        return self



    async def __aexit__(self, exc_type, exc, tb):
        self.logger.info("Exiting async context")
        try:
            self.baresip.quit()
        except:
            self.logger.warning("self-cleanup error; baresip may already have been quit.", exc_info=True)



    #
    # def __del__(self):
    #     try:
    #         self.baresip.quit()
    #     except:
    #         self.logger.warning("self-cleanup error; baresip may already have been quit.", exc_info=True)



if __name__ == "__main__":

    async def main():
        # sip_t = SipTestBaresip(gateway="192.168.7.15", user="pi2", password="pitest", callee="1101",
        #                        post_connect="1234")
        # await sip_t.execute()

        print(f"(main) Current thread ID: {threading.get_ident()}")


        async with SipTestBaresip(gateway="192.168.7.15", user="pi2", password="pitest") as sip_test:
            print(f"(in context) Current thread ID: {threading.get_ident()}")
            await sip_test.execute(callee="1101", post_connect="1234", call_timeout=10)
            print("done!")

    asyncio.get_event_loop().run_until_complete(main())

