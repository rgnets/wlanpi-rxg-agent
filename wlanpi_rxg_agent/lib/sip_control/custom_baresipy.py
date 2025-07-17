import asyncio
import time
from typing import Optional


import pexpect
from baresipy import BareSIP, LOG
from pyee import EventEmitter
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
        self.em = EventEmitter()
        if tts:
            self.tts = tts
        else:
            self.tts = ResponsiveVoice(gender=ResponsiveVoice.MALE)

        # a
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

    def handle_incoming_call(self, number):
        ''' Overrides default so it doesn't automatically handle calls.'''
        LOG.info("Incoming call: " + number)
        time.sleep(0.1)
        self.do_command("b")

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
                        self.em.emit("ready", raw=out, bs_instance=self)
                    elif "account: No SIP accounts found" in out:
                        self._handle_no_accounts()
                        self.em.emit("no_accounts", raw=out, bs_instance=self)
                    elif "All 1 useragent registered successfully!" in out:
                        self.ready = True
                        self.handle_login_success()
                        self.em.emit("login_success", raw=out, bs_instance=self)
                    elif "ua: SIP register failed:" in out or\
                            "401 Unauthorized" in out or \
                            "Register: Destination address required" in out or\
                            "Register: Connection timed out" in out:
                        self.handle_error(out)
                        self.em.emit("error",error=out, raw=out, bs_instance=self)
                        self.handle_login_failure()
                        self.em.emit("login_failure", raw=out, bs_instance=self)
                    elif "Incoming call from: " in out:
                        num = out.split("Incoming call from: ")[
                            1].split(" - (press 'a' to accept)")[0].strip()
                        self.current_call = num
                        self._call_status = "INCOMING"
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                        self.handle_incoming_call(num)
                        self.em.emit("incoming_call", num=num, raw=out, bs_instance=self)
                    elif "call: rejecting incoming call from " in out:
                        num = out.split("rejecting incoming call from ")[1].split(" ")[0].strip()
                        self.handle_call_rejected(num)
                        self.em.emit("rejecting_call", num=num, raw=out, bs_instance=self)
                    elif "call: SIP Progress: 180 Ringing" in out:
                        self.handle_call_ringing()
                        status = "RINGING"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                    elif "call: connecting to " in out:
                        n = out.split("call: connecting to '")[1].split("'")[0]
                        self.current_call = n
                        self.handle_call_start()
                        status = "OUTGOING"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                    elif "Call established:" in out:

                        status = "ESTABLISHED"
                        self.handle_call_status(status)
                        self._call_status = status
                        time.sleep(0.5)
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                        self.handle_call_established()
                        self.em.emit("call_established", raw=out, bs_instance=self)
                    elif "call: hold " in out:
                        n = out.split("call: hold ")[1]
                        status = "ON HOLD"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                    elif "Call with " in out and \
                            "terminated (duration: " in out:
                        status = "DISCONNECTED"
                        duration = out.split("terminated (duration: ")[1][:-1]
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                        self.handle_call_timestamp(duration)
                        self.mic_muted = False
                        self.em.emit("call_terminated", duration=duration, raw=out, bs_instance=self)
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
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                        self.handle_call_ended(reason)
                        self.mic_muted = False
                        self.em.emit("session_closed",reason=reason, raw=out, bs_instance=self)
                    elif "(no active calls)" in out:
                        status = "DISCONNECTED"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
                    elif "===== Call debug " in out:
                        status = out.split("(")[1].split(")")[0]
                        self.handle_call_status(status)
                        self._call_status = status
                        self.em.emit("call_status", status=self._call_status, raw=out, bs_instance=self)
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
                        self.em.emit("error", error=error, raw=out, bs_instance=self)
                    elif "EX=BareSip;" in out:
                        summary_data = {}
                        elements = out.split(";")
                        for element in elements:
                            if "=" in element:
                                key, value = element.split("=")
                                summary_data[key] = value

                        self.handle_rtcp_summary(summary_data)
                        self.em.emit("rtcp_summary", summary=summary_data, raw=out, bs_instance=self)

                    self._prev_output = out
            except pexpect.exceptions.EOF:
                # baresip exited
                self.quit()
            except pexpect.exceptions.TIMEOUT:
                # nothing happened for a while
                pass


    async def async_wait_until_ready(self):
        while not self.ready:
            LOG.debug("Waiting for baresip to be ready...")
            await asyncio.sleep(0.1)
            if self.abort:
                return

    def handle_rtcp_summary(self, summary_data: dict):
        LOG.info(f"Received RTCP summary: {summary_data}")