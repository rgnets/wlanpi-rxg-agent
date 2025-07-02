import asyncio
import time
from typing import Optional

import pexpect
from baresipy import BareSIP, LOG
from responsive_voice import ResponsiveVoice


class CustomBaresipy(BareSIP):
    '''
    Overrides a number of methods in baresipy to provide more control and to fix some bugs.
    '''

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

    def run(self):
        self.running = True
        while self.running:
            try:
                out = self.baresip.readline().decode("utf-8")

                if out != self._prev_output:
                    out = out.strip()
                    if self.debug:
                        LOG.debug(out)
                    if "baresip is ready." in out:
                        self.handle_ready()
                    elif "account: No SIP accounts found" in out:
                        self._handle_no_accounts()
                    elif "All 1 useragent registered successfully!" in out:
                        self.ready = True
                        self.handle_login_success()
                    elif "ua: SIP register failed:" in out or\
                            "401 Unauthorized" in out or \
                            "Register: Destination address required" in out or\
                            "Register: Connection timed out" in out:
                        self.handle_error(out)
                        self.handle_login_failure()
                    elif "Incoming call from: " in out:
                        num = out.split("Incoming call from: ")[
                            1].split(" - (press 'a' to accept)")[0].strip()
                        self.current_call = num
                        self._call_status = "INCOMING"
                        self.handle_incoming_call(num)
                    elif "call: rejecting incoming call from " in out:
                        num = out.split("rejecting incoming call from ")[1].split(" ")[0].strip()
                        self.handle_call_rejected(num)
                    elif "call: SIP Progress: 180 Ringing" in out:
                        self.handle_call_ringing()
                        status = "RINGING"
                        self.handle_call_status(status)
                        self._call_status = status
                    elif "call: connecting to " in out:
                        n = out.split("call: connecting to '")[1].split("'")[0]
                        self.current_call = n
                        self.handle_call_start()
                        status = "OUTGOING"
                        self.handle_call_status(status)
                        self._call_status = status
                    elif "Call established:" in out:

                        status = "ESTABLISHED"
                        self.handle_call_status(status)
                        self._call_status = status
                        time.sleep(0.5)
                        self.handle_call_established()
                    elif "call: hold " in out:
                        n = out.split("call: hold ")[1]
                        status = "ON HOLD"
                        self.handle_call_status(status)
                        self._call_status = status
                    elif "Call with " in out and \
                            "terminated (duration: " in out:
                        status = "DISCONNECTED"
                        duration = out.split("terminated (duration: ")[1][:-1]
                        self.handle_call_status(status)
                        self._call_status = status
                        self.handle_call_timestamp(duration)
                        self.mic_muted = False
                    elif "call muted" in out:
                        self.mic_muted = True
                        self.handle_mic_muted()
                    elif "call un-muted" in out:
                        self.mic_muted = False
                        self.handle_mic_unmuted()
                    elif "session closed:" in out:
                        reason = out.split("session closed:")[1].strip()
                        status = "DISCONNECTED"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.handle_call_ended(reason)
                        self.mic_muted = False
                    elif "(no active calls)" in out:
                        status = "DISCONNECTED"
                        self.handle_call_status(status)
                        self._call_status = status
                    elif "===== Call debug " in out:
                        status = out.split("(")[1].split(")")[0]
                        self.handle_call_status(status)
                        self._call_status = status
                    elif "--- List of active calls (1): ---" in \
                            self._prev_output:
                        if "ESTABLISHED" in out and self.current_call in out:
                            ts = out.split("ESTABLISHED")[0].split(
                                "[line 1]")[1].strip()
                            if ts != self._ts:
                                self._ts = ts
                                self.handle_call_timestamp(ts)
                    elif "failed to set audio-source (No such device)" in out:
                        error = "failed to set audio-source (No such device)"
                        self.handle_error(error)
                    elif "EX=BareSip;" in out:
                        summary_data = {}
                        elements = out.split(";")
                        for element in elements:
                            if "=" in element:
                                key, value = element.split("=")
                                summary_data[key] = value

                        self.handle_rtcp_summary(summary_data)

                    self._prev_output = out
            except pexpect.exceptions.EOF:
                # baresip exited
                self.quit()
            except pexpect.exceptions.TIMEOUT:
                # nothing happened for a while
                pass


    async def async_wait_until_ready(self):
        while not self.ready:
            await asyncio.sleep(0.1)
            if self.abort:
                return

    def handle_rtcp_summary(self, summary_data: dict):
        LOG.info(f"Received RTCP summary: {summary_data}")