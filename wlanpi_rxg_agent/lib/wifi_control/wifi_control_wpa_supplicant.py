import asyncio
import logging
import re
import threading
import time
from asyncio import AbstractEventLoop
from typing import Any, Optional

import utils
import wpa_supplicant
from busses import command_bus, message_bus
from core_client import CoreClient
from lib.wifi_control import domain as wifi_domain
from lib.wifi_control.wifi_control import WifiControl
from models.runcommand_error import RunCommandError
from twisted.internet.asyncioreactor import AsyncioSelectorReactor
from utils import run_command_async
from wpa_supplicant.core import Interface, WpaSupplicant, WpaSupplicantDriver


class WifiInterfaceException(Exception):
    pass


class WifiInterfaceAuthenticationError(WifiInterfaceException):
    pass


class WifiInterfaceDisconnectedError(WifiInterfaceException):
    pass


class WifiInterfaceTimeoutError(WifiInterfaceException):
    pass


class WifiInterface:

    def __init__(
        self,
        name,
        supplicant: WpaSupplicant,
        interface: Interface,
        event_loop: Optional[AbstractEventLoop] = None,
    ):
        self.logger = logging.getLogger(f"{__name__}:")
        self.logger.info(f"Initializing {__name__}")
        self.name = name
        self.supplicant = supplicant
        self.interface = interface

        self.ssid = None
        self.psk = None

        if event_loop is None:
            self.event_loop = asyncio.get_event_loop()
        else:
            self.event_loop = event_loop

        def prop_change_callback(result):
            self.logger.debug(f"MSR: {self.name}: {result}")
            if "State" in result:
                message_bus.handle(
                    wifi_domain.Messages.WpaSupplicantStateChanged(
                        interface=self.name, state=result["State"], details=result
                    )
                )
                # message_bus.handle(wifi_domain.Messages.WifiControlEvent(interface=self.name, details=result))
                if result["State"] == "completed":
                    # message_bus.handle(wifi_domain.Messages.WifiControlEvent(interface=self.name, details=result))
                    self.logger.debug(
                        f"Connection of {self.name} to {self.ssid} with {self.psk} completed"
                    )
                    message_bus.handle(
                        wifi_domain.Messages.Completed(
                            interface=self.name, details=result
                        )
                    )

            elif "DisconnectReason" in result:
                message_bus.handle(
                    wifi_domain.Messages.Disconnection(
                        interface=self.name, details=result
                    )
                )
                if result["DisconnectReason"] == 15:
                    self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
                if result["DisconnectReason"] == 13:
                    self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
            elif "Scanning" in result:
                message_bus.handle(
                    wifi_domain.Messages.ScanningStateChanged(
                        interface=self.name, scanning=result["Scanning"], details=result
                    )
                )
            else:
                self.logger.debug(f"Unhandled event on {self.name}: {result}")
                message_bus.handle(
                    wifi_domain.Messages.WpaSupplicantEvent(
                        interface=self.name, details=result
                    )
                )

        self.prop_signal = self.interface.register_signal(
            "PropertiesChanged", prop_change_callback
        )

    def __del__(self):
        try:
            self.prop_signal.cancel()
        except RuntimeError as e:
            self.logger.warning(
                f"Unable to cancel prop_signal on exit: {e}", exc_info=True
            )

    @property
    def connected(self):
        return self.interface.get_current_network() != None

    #     self._x = x  # _x is a private attribute
    #
    # @property
    # def x(self):  # This becomes the getter for an attribute named 'x'
    #     return self._x
    #
    # @x.setter
    # def x(self, value):  # This is the setter for the same attribute
    #     if not isinstance(value, int):  # Let's also add some validation
    #         raise ValueError('The "x" property must be an integer')
    #     self._x = value

    async def renew_dhcp(self):

        try:
            message_bus.handle(wifi_domain.Messages.DhcpRenewing(interface=self.name))
            self.logger.debug("Renewing DHCP lease on interface %s", self.name)
            # Release the current DHCP lease
            self.logger.debug(f"Releasing current DHCP lease on interface {self.name}")
            await run_command_async(["dhclient", "-r", self.name], raise_on_fail=True)
            time.sleep(3)
            # Obtain a new DHCP lease
            self.logger.debug(f"Requesting new DHCP lease on interface {self.name}")
            await run_command_async(["dhclient", self.name], raise_on_fail=True)
            self.logger.debug(f"New DHCP lease obtained on interface {self.name}")
            message_bus.handle(wifi_domain.Messages.DhcpRenewed(interface=self.name))
        except RunCommandError as err:
            logging.warning(
                f"Failed to renew DHCP. Code:{err.return_code}, Error: {err.error_msg}"
            )
            message_bus.handle(
                wifi_domain.Messages.DhcpRenewalFailed(
                    interface=self.name, message=err.error_msg, exc=err
                )
            )
            return None

    async def remove_default_routes(self):
        """
        Removes the default route for the interface. Primarily used if you used add_default_route for the interface.
        @return: None
        """
        self.logger.debug(f"Removing default routes on {self.name}")
        # Get existing routes for this adapter
        routes: list[dict[str, Any]] = (
            await run_command_async(["ip", "--json", "route"])  # type: ignore
        ).output_from_json()
        for route in routes:
            if route["dev"] == self.name and route["dst"] == "default":
                await run_command_async(
                    ["ip", "route", "del", "default", "dev", self.name]
                )

    @staticmethod
    def parse_lease_file(file_path: str) -> list[dict[str, Any]]:
        body_pattern = re.compile(
            r"lease\s+\{(?P<body>.*?)\}", re.MULTILINE | re.DOTALL
        )
        leases = []
        with open(file_path) as f:
            for match in body_pattern.finditer(f.read()):
                lease: dict[str, dict[str, str]] = {"option": {}}
                for line in match.group("body").split("\n"):
                    data = line.strip().rstrip(";").split(" ", 1)
                    if len(data) > 0:
                        if len(data) == 1 and data[0] == "":
                            continue
                        if data[0] == "option":
                            opt_key, opt_val = data[1].split(" ", 1)
                            lease["option"][opt_key] = opt_val
                        else:
                            if len(data) > 1:
                                lease[data[0]] = data[1]
                            else:
                                lease[data[0]] = ""
                leases.append(lease)
        return leases

    async def add_default_routes(
        self,
        router_addresses: Optional[list[str]] = None,
        metric: Optional[int] = None,
    ) -> list[str]:
        """
        Adds a default route to an interface
        @param router_address: Optionally specify which IP this route is via. If left blank, it will be grabbed from the dhclient lease file.
        @param metric: Optional metric for the route. If left as none, a lowest-priority metric starting at 200 will be calculated unless there are no other default routes.
        @return: A string representing the new default route.
        """
        self.logger.debug(f"Adding default routes on {self.name}")

        interface = self.name

        # Obtain the router address if not manually provided
        self.logger.info(f"Checking lease files for routes for {interface}")
        if router_addresses is None:
            my_lease = None
            base_leases = self.parse_lease_file(f"/var/lib/dhcp/dhclient.leases")
            self.logger.debug("Base leases: " + str(base_leases))
            for lease in sorted(
                [
                    x
                    for x in base_leases
                    if "interface" in x and x["interface"].strip('"') == interface
                ],
                key=lambda d: d["expire"].split(" ", 1)[1],
            ):
                if "interface" in lease and lease["interface"].strip('"') == interface:
                    my_lease = lease
                    break

            if not my_lease:
                subfile_leases = self.parse_lease_file(
                    f"/var/lib/dhcp/dhclient.{interface}.leases"
                )
                self.logger.debug("Subfile leases: " + str(subfile_leases))
                for lease in sorted(
                    [
                        x
                        for x in subfile_leases
                        if "interface" in x and x["interface"].strip('"') == interface
                    ],
                    key=lambda d: d["expire"].split(" ", 1)[1],
                ):
                    if (
                        "interface" in lease
                        and lease["interface"].strip('"') == interface
                    ):
                        my_lease = lease
                        break
            if not my_lease or "routers" not in my_lease["option"]:
                self.logger.error(f"Unable to obtain router address for {interface}")
                raise WifiInterfaceException(
                    f"Unable to obtain router address for {interface}"
                )
            else:
                router_addresses = my_lease["option"]["routers"].split(" ")
                self.logger.info(
                    f"Using router addresses {router_addresses} from lease file"
                )

        new_routes = []
        for router_address in router_addresses:
            # Calculate a new metric if needed
            if metric is None:
                routes: list[dict[str, Any]] = (
                    await run_command_async(["ip", "--json", "route"])  # type: ignore
                ).output_from_json()
                default_routes = [
                    x.get("metric", 0) for x in routes if x["dst"] == "default"
                ]
                if len(default_routes):
                    metric = max(default_routes)
                    if metric < 200:
                        metric = 200
                    else:
                        metric += 1

            # Generate and set new default route
            new_route = f"default via {router_address} dev {interface}"
            if metric:
                new_route += f" metric {metric}"

            command = ["ip", "route", "add", *new_route.split(" ")]
            await run_command_async(command)
            new_routes.append(new_route)
        self.logger.debug(f"Added default routes on {self.name}: {new_routes}")
        return new_routes

    def blocking_scan(self):
        self.logger.debug(f"Performing blocking scan on {self.name}")

        scan_results = self.interface.scan(block=True)
        for bss in scan_results:
            print(bss.get_ssid())

    def remove_all_networks(self):
        self.logger.info(f"Removing all networks from {self.name}")

        for network in self.interface.get_networks():
            self.interface.remove_network(network.get_path())

    async def connect(
        self,
        ssid: str,
        psk: Optional[str] = None,
        key_mgmt: str = "WPA-PSK",
        proto: str = "WPA2",
        timeout: float = 20,
    ):
        self.logger.info(f"Connecting {self.name} to {ssid}")
        add_network_future = self.event_loop.create_future()
        signal = None
        states = []

        def prop_change_callback(result):
            # self.logger.debug(f"{self.name}: {result}")
            if "State" in result:
                states.append(result)
                if result["State"] == "completed":
                    self.logger.debug(f"Connection to {ssid} completed")
                    add_network_future.set_result(states)
            if "DisconnectReason" in result:
                if result["DisconnectReason"] == 15:
                    # self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
                    add_network_future.set_exception(
                        WifiInterfaceAuthenticationError(
                            f"An authentication error occurred: {states}"
                        )
                    )
                if result["DisconnectReason"] == 13:
                    # self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
                    add_network_future.set_exception(
                        WifiInterfaceDisconnectedError(
                            f"A disconnection occurred: {states}"
                        )
                    )

        self.remove_all_networks()

        net_cfg = {
            "ssid": ssid,
            "scan_ssid": 1,
            # "disabled":0,
            "ieee80211w": 1,  # Default to optional protected mgmt frames
        }
        if psk:
            net_cfg["psk"] = psk
            net_cfg["key_mgmt"] = key_mgmt
            net_cfg["proto"] = proto

        self.ssid = ssid
        self.psk = psk

        signal = self.interface.register_signal(
            "PropertiesChanged", prop_change_callback
        )
        add_res = self.interface.add_network(net_cfg)
        new_net = self.interface.get_networks()[0]
        self.interface.select_network(new_net.get_path())

        # PropertiesChanged
        try:
            return await asyncio.wait_for(
                asyncio.shield(add_network_future), timeout=timeout
            )
        except (
            asyncio.TimeoutError,
            TimeoutError,
            asyncio.exceptions.CancelledError,
        ) as e:
            self.logger.warning(f"Timeout connecting {self.name} to {ssid}")
            raise TimeoutError(f"Timeout connecting {self.name} to {ssid}")
        finally:
            signal.cancel()

    def disconnect(self):
        self.logger.info(f"Disconnecting {self.name}")
        self.interface.disconnect_network()


class WiFiControlWpaSupplicant(WifiControl):

    def __init__(self, event_loop: Optional[AbstractEventLoop] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        if event_loop is None:
            self.event_loop = asyncio.get_event_loop()
            # self.event_loop = asyncio.new_event_loop()
        else:
            self.event_loop = event_loop
        # self.reactor = AsyncioSelectorReactor(eventloop=self.event_loop)
        self.logger.debug("Setting up reactor")
        self.reactor = AsyncioSelectorReactor(eventloop=asyncio.new_event_loop())
        # self.reactor = AsyncioSelectorReactor()
        # self.reactor.install()
        self.logger.debug("Starting reactor")
        self.reactor_thread = threading.Thread(
            target=self.reactor.run, kwargs={"installSignalHandlers": 0}
        )
        self.reactor_thread.start()
        self.reactor._justStopped = False
        # Let the reactor start
        time.sleep(0.1)
        self.current_adapter_config = {}

        self.logger.debug("Starting Driver")
        # Start Driver
        self.driver = WpaSupplicantDriver(self.reactor)
        self.logger.debug("Connecting to driver")

        # Start a timeout task--if connection fails, restart the supplicant and try again.

        # Connect to the supplicant, which returns the "root" D-Bus object for wpa_supplicant
        # self.supplicant = self.driver.connect()
        tries = 3
        while tries > 0:
            try:
                self.supplicant = self._connect_with_timeout(timeout=10)
                break
            except Exception as e:
                self.logger.exception("Failed to connect to wpa_supplicant:")
                self.restart_wpa_supplicant()
                time.sleep(10)
                tries -= 1
        if not self.supplicant:
            raise Exception("Could not connect to wpa_supplicant after 3 attempts")

        self.interfaces = {}

        self.logger.debug("Setting up listeners")
        self.command_handler_pairs = (
            (
                wifi_domain.Commands.GetOrCreateInterface,
                lambda event: self.get_or_create_interface(event.if_name),
            ),
        )
        self.setup_listeners()

    def setup_listeners(self):
        # TODO: Surely we can implement this as some sort of decorator function?
        for command, handler in self.command_handler_pairs:
            command_bus.add_handler(command, handler)

    def teardown_listeners(self):
        # TODO: Surely we can implement this as some sort of decorator function?
        for command, handler in self.command_handler_pairs:
            command_bus.remove_handler(command)

    def _connect_with_timeout(self, timeout=10):
        """Connects to wpa_supplicant with a timeout, without reactor access."""

        def connect_in_thread():
            """The actual connection logic, running in a separate thread."""
            try:
                res = self.driver.connect()
                self.logger.info("I did actually connect")
                return res
            except Exception as e:
                self.logger.exception(f"Error in connect_in_thread:")
                raise  # Re-raise to be caught by the caller

        result = None  # This will hold the result
        finished_event = threading.Event()

        def threaded_connect():
            nonlocal result  # Crucial: Access the outer scope's result
            try:
                result = connect_in_thread()
            except (
                Exception
            ) as e:  # Catch and log the exception, then re-raise to trigger the timeout handling
                self.logger.exception("Failed to connect in thread:")
            finally:  # Ensure the event is set even if an exception occurs.
                finished_event.set()

        connect_thread = threading.Thread(target=threaded_connect)
        connect_thread.start()

        if finished_event.wait(
            timeout
        ):  # Check if the event was set within the timeout
            return result
        else:
            raise TimeoutError("Connection timed out.")

    def restart_wpa_supplicant(self):
        """Restarts the wpa_supplicant service."""
        try:
            print("Restarting wpa_supplicant service...")
            utils.run_command(
                ["systemctl", "restart", "wpa_supplicant"]
            )  # Or appropriate command for your system
            print("wpa_supplicant restarted.")
        except (utils.RunCommandError, utils.RunCommandTimeout) as e:
            print(f"Error restarting wpa_supplicant: {e}")

    # def __del__(self):
    #     self.reactor.stop()
    #     self.reactor_thread.join(timeout=4)

    def shutdown(self):
        self.logger.info(f"Shutting down {__name__}")
        self.teardown_listeners()
        self.reactor.stop()
        self.reactor_thread.join(timeout=4)
        self.logger.info(f"{__name__} shutdown complete.")

    def get_or_create_interface(self, interface_name):

        if interface_name not in self.interfaces:
            try:
                self.interfaces[interface_name] = WifiInterface(
                    interface_name,
                    self.supplicant,
                    self.supplicant.create_interface(interface_name),
                    event_loop=self.event_loop,
                )
            except wpa_supplicant.core.InterfaceExists as e:
                self.logger.info(
                    f"Interface {interface_name} already exists; adding to list."
                )
                self.interfaces[interface_name] = WifiInterface(
                    interface_name,
                    self.supplicant,
                    self.supplicant.get_interface(interface_name),
                    event_loop=self.event_loop,
                )

        return self.interfaces[interface_name]


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

    async def main():
        wc = WiFiControlWpaSupplicant()
        interface_name = "wlan2"
        wlan_if = wc.get_or_create_interface(interface_name)
        # wlan_if.blocking_scan()
        # pprint(wlan_if.interface.get_networks())
        # pprint(wlan_if.interface.get_current_network())
        #
        # try:
        #
        #     await wlan_if.connect("network", "password")
        # except WifiInterfaceAuthenticationError as e:
        #     logger.error(e)
        # except WifiInterfaceTimeoutError as e:
        #     logger.error("Timeout connecting")
        # # wlan_if.blocking_scan()
        # pprint(wlan_if.interface.get_current_network())

        await wlan_if.connect(ssid="anetwork", psk="apassword")
        logger.info(f"Connection state of {interface_name} is complete. Renewing dhcp.")
        await wlan_if.renew_dhcp()
        # self.logger.info(f"Waiting for dhcp to settle.")
        # await asyncio.sleep(5)
        logger.info(f"Adding default routes for {interface_name}.")
        await wlan_if.add_default_routes()
        print("Done")

        print("stop here?")

    global mainproc
    mainproc = main()
    asyncio.get_event_loop().run_until_complete(mainproc)
