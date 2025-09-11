import asyncio
import enum
import logging
import subprocess
import tempfile
from os.path import expanduser, join
from threading import Thread
from time import sleep, time
from typing import Coroutine, Optional

import pexpect
from opentone import ToneGenerator
from pydub import AudioSegment
from pyee import EventEmitter
from pyee.asyncio import AsyncIOEventEmitter
from responsive_voice import ResponsiveVoice

from wlanpi_rxg_agent.utils import run_command_async

# from .utils import create_daemon

logging.getLogger("urllib3.connectionpool").setLevel("WARN")
logging.getLogger("pydub.converter").setLevel("WARN")


class MdkBareSIP:
    class Events(enum.Enum):
        ESTABLISHED = "call_established"
        CALL_STATUS = "call_status"
        TERMINATED = "call_terminated"
        ERROR = "error"
        INCOMING = "incoming_call"
        LOGIN_FAILURE = "login_failure"
        LOGIN_SUCCESS = "login_success"
        NO_ACCOUNTS = "no_accounts"
        READY = "ready"
        REJECTING = "rejecting_call"
        SUMMARY = "rtcp_summary"
        SESSION_CLOSED = "session_closed"
        QUIT = "quit"
        TIMEOUT = "timeout"

    def __init__(
        self,
        user,
        pwd,
        gateway,
        tts=None,
        debug=False,
        extra_login_args: Optional[str] = None,
        config_path: Optional[str] = None,
        interface: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.debug = debug
        self.user = user
        self.pwd = pwd
        self.gateway = gateway
        self.async_loop = loop or asyncio.get_event_loop()

        self.ee = AsyncIOEventEmitter(loop=self.async_loop)

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

        self._bs_args = ["-c"]

        if config_path:
            self._bs_args.extend(["-f", config_path])

        if interface:
            self._bs_args.extend(["-n", interface])

        self.baresip = pexpect.spawn("baresip", args=self._bs_args)

        # Patch in an async readline method
        async def readline_async(self: pexpect.pty_spawn.spawn, size=-1):
            if size == 0:
                return self.string_type()
            # delimiter default is EOF
            index = await self.expect([self.crlf, self.delimiter], async_=True)
            if index == 0:
                return self.before + self.crlf
            else:
                return self.before

        bound_readline_async = readline_async.__get__(
            self.baresip, pexpect.pty_spawn.spawn
        )
        setattr(self.baresip, "readline_async", bound_readline_async)
        self.logger.debug("Baresip initialized!")

        self.run_task: Optional[Coroutine] = None

    @staticmethod
    async def setup_pi():
        """Performs some setup steps required for doing this on a headless pi"""
        dummy_sound = "modprobe snd-dummy fake_buffer=0"
        await run_command_async(dummy_sound)

    # properties
    @property
    def call_established(self):
        return self.call_status == "ESTABLISHED"

    @property
    def call_status(self):
        return self._call_status or "DISCONNECTED"

    # actions
    def do_command(self, action):
        if self.ready:
            action = str(action)
            self.baresip.sendline(action)
        else:
            self.logger.warning(action + " not executed!")
            self.logger.error("NOT READY! please wait")

    def login(self):
        self.logger.info("Adding account: " + self.user)
        self.baresip.sendline("/uanew " + self._login)

    def call(self, number):
        self.logger.info("Dialling: " + number)
        self.do_command("/dial " + number)

    def hang(self):
        if self.current_call:
            self.logger.info("Hanging: " + self.current_call)
            self.do_command("/hangup")
            self.current_call = None
            self._call_status = None
        else:
            self.logger.error("No active call to hang")

    def hold(self):
        if self.current_call:
            self.logger.info("Holding: " + self.current_call)
            self.do_command("/hold")
        else:
            self.logger.error("No active call to hold")

    def resume(self):
        if self.current_call:
            self.logger.info("Resuming " + self.current_call)
            self.do_command("/resume")
        else:
            self.logger.error("No active call to resume")

    def mute_mic(self):
        if not self.call_established:
            self.logger.error("Can not mute microphone while not in a call")
            return
        if not self.mic_muted:
            self.logger.info("Muting mic")
            self.do_command("/mute")
        else:
            self.logger.info("Mic already muted")

    def unmute_mic(self):
        if not self.call_established:
            self.logger.error("Can not unmute microphone while not in a call")
            return
        if self.mic_muted:
            self.logger.info("Unmuting mic")
            self.do_command("/mute")
        else:
            self.logger.info("Mic already unmuted")

    def accept_call(self):
        self.do_command("/accept")
        status = "ESTABLISHED"
        self.handle_call_status(status)
        self._call_status = status

    def list_calls(self):
        self.do_command("/listcalls")

    def check_call_status(self):
        self.do_command("/callstat")
        sleep(0.1)
        return self.call_status

    def quit(self):
        self.logger.info("Exiting")
        if self.running:
            if self.current_call:
                self.hang()
            self.baresip.sendline("/quit")
        self.running = False
        self.current_call = None
        self._call_status = None
        self.abort = True

    def send_dtmf(self, number):
        number = str(number)
        for n in number:
            if n not in "0123456789":
                self.logger.error("invalid dtmf tone")
                return
        self.logger.info("Sending dtmf tones for " + number)
        dtmf = join(tempfile.gettempdir(), number + ".wav")
        ToneGenerator().dtmf_to_wave(number, dtmf)
        self.send_audio(dtmf)

    def speak(self, speech):
        if not self.call_established:
            self.logger.error("Speaking without an active call!")
        else:
            self.logger.info("Sending TTS for " + speech)
            self.send_audio(self.tts.get_mp3(speech))
            sleep(0.5)

    def send_audio(self, wav_file):
        if not self.call_established:
            self.logger.error("Can't send audio without an active call!")
            return
        wav_file, duration = self.convert_audio(wav_file)
        # send audio stream
        self.logger.info("transmitting audio")
        self.do_command("/ausrc aufile," + wav_file)
        # wait till playback ends
        sleep(duration - 0.5)
        # avoid baresip exiting
        self.do_command("/ausrc alsa,default")

    @staticmethod
    def convert_audio(input_file, outfile=None):
        input_file = expanduser(input_file)
        sound = AudioSegment.from_file(input_file)
        sound += AudioSegment.silent(duration=500)
        # ensure minimum time
        # workaround baresip bug
        while sound.duration_seconds < 3:
            sound += AudioSegment.silent(duration=500)

        outfile = outfile or join(tempfile.gettempdir(), "pybaresip.wav")
        sound = sound.set_frame_rate(48000)
        sound = sound.set_channels(2)
        sound.export(outfile, format="wav")
        return outfile, sound.duration_seconds

    # this is played out loud over speakers
    def say(self, speech):
        if not self.call_established:
            self.logger.warning("Speaking without an active call!")
        self.tts.say(speech, blocking=True)

    def play(self, audio_file, blocking=True):
        if not audio_file.endswith(".wav"):
            audio_file, duration = self.convert_audio(audio_file)
        self.audio = self._play_wav(audio_file, blocking=blocking)

    def stop_playing(self):
        if self.audio is not None:
            self.audio.kill()

    @staticmethod
    def _play_wav(wav_file, play_cmd="aplay %1", blocking=False):
        play_mp3_cmd = str(play_cmd).split(" ")
        for index, cmd in enumerate(play_mp3_cmd):
            if cmd == "%1":
                play_mp3_cmd[index] = wav_file
        if blocking:
            return subprocess.call(play_mp3_cmd)
        else:
            return subprocess.Popen(play_mp3_cmd)

    """ Event handlers"""
    if True:
        """Event handlers"""

        # events
        def handle_incoming_call(self, number):
            self.logger.info("Incoming call: " + number)
            if self.call_established:
                self.logger.info("already in a call, rejecting")
                sleep(0.1)
                self.do_command("b")
            else:
                self.logger.info("default behaviour, rejecting call")
                sleep(0.1)
                self.do_command("b")

        def handle_call_rejected(self, number):
            self.logger.info("Rejected incoming call: " + number)

        def handle_call_timestamp(self, timestr):
            self.logger.info("Call time: " + timestr)

        def handle_call_status(self, status):
            if status != self._call_status:
                self.logger.debug("Call Status: " + status)

        def handle_call_start(self):
            number = self.current_call
            self.logger.info("Calling: " + number)

        def handle_call_ringing(self):
            number = self.current_call
            self.logger.info(number + " is Ringing")

        def handle_call_established(self):
            self.logger.info("Call established")

        def handle_call_ended(self, reason):
            self.logger.info("Call ended")
            self.logger.debug("Reason: " + reason)

        def _handle_no_accounts(self):
            self.logger.debug("No accounts setup")
            self.login()

        def handle_login_success(self):
            self.logger.info("Logged in!")

        def handle_login_failure(self):
            self.logger.error("Log in failed!")
            self.quit()

        def handle_ready(self):
            self.logger.info("Ready for instructions")

        def handle_mic_muted(self):
            self.logger.info("Microphone muted")

        def handle_mic_unmuted(self):
            self.logger.info("Microphone unmuted")

        def handle_audio_stream_failure(self):
            self.logger.debug("Aborting call, maybe we reached voicemail?")
            self.hang()

        def handle_error(self, error):
            self.logger.error(error)
            if error == "failed to set audio-source (No such device)":
                self.handle_audio_stream_failure()

    # event loop
    async def run(self):
        self.logger.debug("Starting event loop")
        self.running = True
        while self.running:
            self.logger.debug("Waiting for output")
            try:
                out = (await self.baresip.readline_async()).decode("utf-8")

                if out != self._prev_output:
                    out = out.strip()
                    if self.debug:
                        self.logger.debug(out)
                    if "baresip is ready." in out:
                        self.handle_ready()
                        self.ee.emit(str(self.Events.READY), raw=out, bs_instance=self)
                    elif "account: No SIP accounts found" in out:
                        self._handle_no_accounts()
                        self.ee.emit(
                            str(self.Events.NO_ACCOUNTS), raw=out, bs_instance=self
                        )
                    elif "All 1 useragent registered successfully!" in out:
                        self.ready = True
                        self.handle_login_success()
                        self.ee.emit(
                            str(self.Events.LOGIN_SUCCESS), raw=out, bs_instance=self
                        )
                    elif (
                        "ua: SIP register failed:" in out
                        or "401 Unauthorized" in out
                        or "Register: Destination address required" in out
                        or "Register: Connection timed out" in out
                    ):
                        self.handle_error(out)
                        self.ee.emit(
                            str(self.Events.ERROR), error=out, raw=out, bs_instance=self
                        )
                        self.handle_login_failure()
                        self.ee.emit(
                            str(self.Events.LOGIN_FAILURE), raw=out, bs_instance=self
                        )
                    elif "Incoming call from: " in out:
                        num = (
                            out.split("Incoming call from: ")[1]
                            .split(" - (press 'a' to accept)")[0]
                            .strip()
                        )
                        self.current_call = num
                        self._call_status = "INCOMING"
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                        self.handle_incoming_call(num)
                        self.ee.emit(
                            str(self.Events.REJECTING),
                            num=num,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "call: rejecting incoming call from " in out:
                        num = (
                            out.split("rejecting incoming call from ")[1]
                            .split(" ")[0]
                            .strip()
                        )
                        self.handle_call_rejected(num)
                        self.ee.emit(
                            str(self.Events.REJECTING),
                            num=num,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "call: SIP Progress: 180 Ringing" in out:
                        self.handle_call_ringing()
                        status = "RINGING"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "call: connecting to " in out:
                        n = out.split("call: connecting to '")[1].split("'")[0]
                        self.current_call = n
                        self.handle_call_start()
                        status = "OUTGOING"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "Call established:" in out:

                        status = "ESTABLISHED"
                        self.handle_call_status(status)
                        self._call_status = status
                        await asyncio.sleep(0.5)
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                        self.handle_call_established()
                        self.ee.emit(
                            str(self.Events.ESTABLISHED), raw=out, bs_instance=self
                        )
                    elif "call: hold " in out:
                        n = out.split("call: hold ")[1]
                        status = "ON HOLD"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "Call with " in out and "terminated (duration: " in out:
                        status = "DISCONNECTED"
                        duration = out.split("terminated (duration: ")[1][:-1]
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                        self.handle_call_timestamp(duration)
                        self.mic_muted = False
                        self.ee.emit(
                            str(self.Events.TERMINATED),
                            duration=duration,
                            raw=out,
                            bs_instance=self,
                        )
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
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                        self.handle_call_ended(reason)
                        self.mic_muted = False
                        self.ee.emit(
                            str(self.Events.SESSION_CLOSED),
                            reason=reason,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "(no active calls)" in out:
                        status = "DISCONNECTED"
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "===== Call debug " in out:
                        status = out.split("(")[1].split(")")[0]
                        self.handle_call_status(status)
                        self._call_status = status
                        self.ee.emit(
                            str(self.Events.CALL_STATUS),
                            status=self._call_status,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "--- List of active calls (1): ---" in self._prev_output:
                        if "ESTABLISHED" in out and self.current_call in out:
                            ts = (
                                out.split("ESTABLISHED")[0].split("[line 1]")[1].strip()
                            )
                            if ts != self._ts:
                                self._ts = ts
                                self.handle_call_timestamp(ts)
                    elif "failed to set audio-source (No such device)" in out:
                        error = "failed to set audio-source (No such device)"
                        self.handle_error(error)
                        self.ee.emit(
                            str(self.Events.ERROR),
                            error=error,
                            raw=out,
                            bs_instance=self,
                        )
                    elif "EX=BareSip;" in out:
                        summary_data = {}
                        elements = out.split(";")
                        for element in elements:
                            if "=" in element:
                                key, value = element.split("=")
                                summary_data[key] = value

                        self.handle_rtcp_summary(summary_data)
                        self.ee.emit(
                            str(self.Events.SUMMARY),
                            summary=summary_data,
                            raw=out,
                            bs_instance=self,
                        )

                    self._prev_output = out
            except pexpect.exceptions.EOF:
                # baresip exited
                self.quit()
                self.ee.emit(str(self.Events.QUIT), raw="", bs_instance=self)
            except pexpect.exceptions.TIMEOUT:
                # nothing happened for a while
                self.ee.emit(str(self.Events.TIMEOUT), raw="", bs_instance=self)
                pass

    async def async_wait_until_ready(self):
        while not self.ready:
            self.logger.debug("Waiting for baresip to be ready...")
            await asyncio.sleep(1)
            if self.abort:
                return

    def handle_rtcp_summary(self, summary_data: dict):
        self.logger.info(f"Received RTCP summary: {summary_data}")

    def wait_until_ready(self):
        while not self.ready:
            sleep(0.1)
            if self.abort:
                return

    async def __aenter__(self):
        self.logger.info("Entering async context")

        self.run_task = asyncio.create_task(self.run())
        try:
            await asyncio.wait_for(self.async_wait_until_ready(), 30)
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout waiting for Baresip to be ready")
            raise
        self.logger.info("Baresip is ready")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.logger.info("Exiting async context")
        try:
            self.quit()
            self.logger.info("Waiting for baresip to quit...")
            await self.ee.wait_for_complete()
            await self.run_task
        except:
            self.logger.warning(
                "self-cleanup error; baresip may already have been quit.", exc_info=True
            )

    async def wait_for_event(self, event_type: Events, event_data):
        pass
