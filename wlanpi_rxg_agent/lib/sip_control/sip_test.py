import asyncio
import logging
import time
from typing import Optional

from lib.sip_control.custom_baresipy import CustomBaresipy
from lib.sip_control.sip_control import SipInstance


class SipTestBaresip(SipInstance):

    def __init__(self,
                 gateway:str,
                 user: str,
                 password: str,
                 callee: str,
                 post_connect: Optional[str] = None,
                 call_timeout: Optional[int] = None,
                 extra_login_args: Optional[str] = None,
                 debug: bool=False
                 ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self._gateway = gateway
        self._user = user
        self._password = password
        self.callee = callee
        self.post_connect = post_connect
        self._extra_login_args = f""
        self.custom_baresip = self.build_custom_baresip_class()
        self.baresip = self.custom_baresip(user = self._user, pwd=self._password, gateway=self._gateway, block=True, debug=debug)
        # self.baresip = CustomBaresipy(user = self._user, pwd=self._password, gateway=self._gateway, block=True, debug=debug)
        # self.baresip.start()
        self.logger.info("Baresip started")


    def build_custom_baresip_class(self):
        my_self = self
        class CustomizedBaresipy(CustomBaresipy):

            def handle_rtcp_summary(self, summary_data: dict):
                my_self.logger.info(f"Received RTCP summary: {summary_data}")

            def handle_call_established(self):
                if my_self.post_connect:
                    my_self.baresip.send_dtmf(my_self.post_connect)
                my_self.baresip.speak("Your mom's a hoe.")
                time.sleep(0.5)
                my_self.baresip.hang()
                my_self.baresip.quit()

        return CustomizedBaresipy


    async def execute(self):
        self.logger.info(f"Executing test against {self.callee}")
        self.baresip.call(self.callee)
        # Dirty hack for now, don't keep this shit.
        while self.baresip.running:
            time.sleep(0.5)
        # self.baresip.quit()


    def __del__(self):
        try:
            self.baresip.quit()
        except:
            self.logger.warning("self-cleanup error; baresip may already have been quit.", exc_info=True)



if __name__ == "__main__":

    async def main():
        sip_t = SipTestBaresip(gateway="192.168.7.15", user="pi2", password="pitest", callee="1101",
                               post_connect="1234")
        await sip_t.execute()

    asyncio.get_event_loop().run_until_complete(main())

