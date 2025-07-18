import asyncio
import logging
import os
from os import PathLike
from typing import Callable, Optional

from wlanpi_rxg_agent import utils
from wlanpi_rxg_agent.lib.sip_control.custom_baresipy import CustomBaresipy
from wlanpi_rxg_agent.lib.sip_control.mdk_baresip import MdkBareSIP
from wlanpi_rxg_agent.lib.sip_control.sip_test import SipTest


class SipTestBaresip(SipTest):

    def __init__(
        self,
        gateway: str,
        user: str,
        password: str,
        extra_login_args: Optional[str] = None,
        debug: bool = False,
        config_path: Optional[PathLike] = None,
        interface: Optional[str] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self._gateway = gateway
        self._user = user
        self._password = password
        self._debug = debug
        self._extra_login_args = extra_login_args
        self._config_path = config_path
        self._interface = interface
        self.logger.info("SipTestBaresip initialized")

    @staticmethod
    async def deploy_config(dest: PathLike = "/tmp/bs/"):
        """
        Loads baresip.conf from the script's directory and writes it to /tmp/bs.conf.
        """
        try:
            # Get the absolute path of the directory containing this script
            script_dir = os.path.dirname(os.path.abspath(__file__))

            # Construct the full path to the source and destination files
            source_file = os.path.join(script_dir, "baresip.conf")

            if not os.path.exists(dest):
                os.mkdir(dest)

            # Read the content from the source file
            with open(source_file, "r") as src:
                content = src.read()

            # Manipulate file here if needed.

            # Write the content to the destination file
            with open(f"{dest}/config", "w") as dest_file:
                dest_file.write(content)

            print(f"Successfully deployed {source_file} to {dest}")

        except FileNotFoundError:
            print(f"Error: Could not find {source_file}")
        except Exception as e:
            print(f"An error occurred: {e}")

    async def execute(
        self,
        callee: str,
        post_connect: Optional[str] = None,
        call_timeout: Optional[int] = None,
        summary_callback: Optional[Callable] = None,
    ):
        await MdkBareSIP.setup_pi()  # Set up dummy sound device
        async with MdkBareSIP(
            gateway=self._gateway,
            user=self._user,
            pwd=self._password,
            debug=self._debug,
            extra_login_args=self._extra_login_args,
            config_path=self._config_path,
            interface=self._interface,
        ) as bs:
            self.logger.info(f"Executing test against {callee}")

            loop = asyncio.get_running_loop()
            call_in_progress = loop.create_future()
            test_in_progress = loop.create_future()
            summary_future = loop.create_future()

            @bs.ee.listens_to(str(bs.Events.SUMMARY))
            def handle_rtcp_summary(summary: dict, *_, **__):
                self.logger.info(f"Received RTCP summary: {summary}")
                summary_future.set_result(summary)

            @bs.ee.listens_to(str(bs.Events.ESTABLISHED))
            async def call_established(bs_instance: MdkBareSIP, *_, **__):
                self.logger.info("call established")
                if post_connect:
                    bs_instance.send_dtmf(post_connect)

                """ CALL TEST LOGIC HERE"""
                bs_instance.speak("I am WLAN Pi " + utils.get_hostname())
                # await asyncio.sleep(0.5)
                # bs_instance.hang()

                """ END CALL TEST LOGIC """
                # If there's no timeout set, always hang up to prevent holding the call open.
                # You can safely hang up before this.
                if not call_timeout:
                    bs_instance.hang()
                if not (test_in_progress.done() or test_in_progress.cancelled()):
                    test_in_progress.set_result(True)

            @bs.ee.listens_to(str(bs.Events.SESSION_CLOSED))
            def handle_call_ended_abnormally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended abnormally")
                # self.logger.debug((call_in_progress.done(), call_in_progress.cancelled()))
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.set_result(False)

            @bs.ee.listens_to(str(bs.Events.TERMINATED))
            def handle_call_ended_normally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended normally")
                # print((call_in_progress.done(), call_in_progress.cancelled()))
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.set_result(True)

            bs.call(callee)

            self.logger.info("Waiting for call to end")
            try:
                # Wait for both the test itself to end, and the call.
                # In some cases, the test won't end until the call does, or it is timed out.
                call_futures = asyncio.gather(call_in_progress, test_in_progress)
                if call_timeout:
                    await asyncio.wait_for(call_futures, timeout=call_timeout)
                else:
                    await call_futures
                self.logger.info("Test completed")
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Call timed out after {call_timeout} seconds. Forcibly hanging up."
                )
                bs.hang()
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.cancel(msg="Test timeout reached.")
                if not (test_in_progress.done() or test_in_progress.cancelled()):
                    test_in_progress.cancel(msg="Test timeout reached.")

            try:
                # Wait a few seconds for the summary to appear.
                summary = await asyncio.wait_for(summary_future, timeout=4)
                return summary
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"No summary received after {call_timeout} seconds."
                )
                raise Exception("No summary received after call timeout.")


if __name__ == "__main__":

    async def main():
        sip_test = SipTestBaresip(
            gateway="192.168.7.15", user="pi2", password="pitest", debug=True
        )
        await sip_test.execute(callee="1101", post_connect="1234", call_timeout=2)
        print("done!")

    asyncio.get_event_loop().run_until_complete(main())
