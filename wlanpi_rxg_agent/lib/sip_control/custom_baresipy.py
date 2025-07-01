from typing import Optional

import pexpect
from baresipy import BareSIP, LOG
from responsive_voice import ResponsiveVoice


class CustomBaresipy(BareSIP):

    def __init__(self, user, pwd, gateway, tts=None, debug=False, block=True, extra_login_args: Optional[str]=None):
        self.debug = debug
        self.user = user
        self.pwd = pwd
        self.gateway = gateway
        if tts:
            self.tts = tts
        else:
            self.tts = ResponsiveVoice(gender=ResponsiveVoice.MALE)

        # /uanew sip:pi2@192.168.7.15;regint=30;auth_pass=pitest;outbound=sip:192.168.7.15;sipnat=outbound
        self._login = f"sip:{self.user}@{self.gateway};auth_pass={self.pwd}"
        if extra_login_args:
            self._login += f";{extra_login_args}"
        self._prev_output = ""
        self.running = False
        self.ready = False
        self.mic_muted = False
        self.abort = False
        self.current_call = None
        self._call_status = None
        self.audio = None
        self._ts = None
        self.baresip = pexpect.spawn('baresip')
        super(BareSIP, self).__init__()
        self.start()
        if block:
            self.wait_until_ready()

    # def login(self):
    #     LOG.info("Adding account: " + self.user)
    #     self.baresip.sendline("/uanew " + self._login)