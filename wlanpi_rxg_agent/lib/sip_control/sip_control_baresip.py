import asyncio
import logging
import time
from asyncio import sleep
from symbol import while_stmt
from typing import Optional

from lib.sip_control.custom_baresipy import CustomBaresipy
from lib.sip_control.sip_control import SipControl, SipInstance

class SipInstanceBaresip(SipInstance):

    def __init__(self, gateway:str, user: str, password: str, extra_login_args: Optional[str] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self._gateway = gateway
        self._user = user
        self._password = password
        self._extra_login_args = f""
        self.baresip = CustomBaresipy(user = self._user, pwd=self._password, gateway=self._gateway, block=True, debug=True)
        # self.baresip.start()
        self.logger.info("Baresip started")


    def call(self, callee: str):
        self.logger.info(f"Calling {callee}")
        b = self.baresip
        b.call(callee)

        while b.running:
            time.sleep(0.5)
            # asyncio.sleep(0.5)
            if b.call_established:
                b.send_dtmf("1234")
                b.speak("Your mom's a hoe.")
                time.sleep(0.5)
                b.hang()
                break


    def __del__(self):
        self.baresip.quit()




class SipControlBaresip(SipControl):

    def __init__(self):

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        #
        # self.baresip_cmd = "/usr/bin/baresip"
        self.instances: dict[tuple[str, str, str], SipInstanceBaresip] = {}

    def get_instance(self, gateway:str, user: str, password: str) -> SipInstanceBaresip:
        ident_tuple = (gateway,user,password)

        if ident_tuple in self.instances:
            self.logger.debug(f"Returning existing instance for {gateway} {user} {password}")
            return self.instances[ident_tuple]

        self.logger.debug(f"Creating new instance for {gateway} {user} {password}")
        instance = SipInstanceBaresip(gateway=gateway, user=user, password=password, extra_login_args=f";regint=30;outbound=sip:{gateway};sipnat=outbound")
        self.instances[ident_tuple] = instance
        return instance

        






if __name__ == "__main__":
    sip_c = SipControlBaresip()

    sip_i = sip_c.get_instance(gateway="192.168.7.15", user="pi2", password="pitest")
    sip_i.call("1101")
    sip_i.baresip.quit()

