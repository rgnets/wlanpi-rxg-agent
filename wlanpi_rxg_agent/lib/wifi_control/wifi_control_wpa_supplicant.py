import asyncio
import logging
from asyncio import AbstractEventLoop
from pprint import pprint
from typing import Optional


import wpa_supplicant
from twisted.internet.asyncioreactor import AsyncioSelectorReactor

from core_client import CoreClient
from lib.wifi_control.wifi_control import WifiControl
from wpa_supplicant.core import WpaSupplicantDriver, WpaSupplicant, Interface
import threading
import time

from models.runcommand_error import RunCommandError
from utils import run_command_async


class WifiInterfaceException(Exception):
    pass

class WifiInterfaceAuthenticationError(WifiInterfaceException):
    pass

class WifiInterfaceDisconnectedError(WifiInterfaceException):
    pass
class WifiInterfaceTimeoutError(WifiInterfaceException):
    pass


class WifiInterface():

    def __init__(self,name, supplicant: WpaSupplicant, interface:Interface, event_loop: Optional[AbstractEventLoop] = None):
        self.logger = logging.getLogger(f"{__name__}:")
        self.logger.info(f"Initializing {__name__}")
        self.name = name
        self.supplicant =supplicant
        self.interface = interface

        self.ssid = None
        self.psk = None
        # self.encryption = None
        # self.authentication = None

        # self.connected = False

        if event_loop is None:
            self.event_loop = asyncio.get_event_loop()
        else:
            self.event_loop = event_loop

    #     def prop_change_callback(result):
    #         # self.logger.debug(f"{self.name}: {result}")
    #         if "State" in result:
    #             if result["State"] == "completed":
    #                 self.connected = True
    #         if "DisconnectReason" in result:
    #             self.connected = False
    #
    #
    #     self.prop_signal = self.interface.register_signal('PropertiesChanged', prop_change_callback)
    #
    # def __del__(self):
    #     try:
    #         self.prop_signal.cancel()
    #     except RuntimeError as e:
    #         self.logger.warning(f"Unable to cancel prop_signal on exit: {e}", exc_info=e)
    #

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
            # Release the current DHCP lease
            await run_command_async(["dhclient", "-r", self.name], raise_on_fail=True)
            time.sleep(3)
            # Obtain a new DHCP lease
            await run_command_async(["dhclient", self.name], raise_on_fail=True)
        except RunCommandError as err:
            logging.warning(
                f"Failed to renew DHCP. Code:{err.return_code}, Error: {err.error_msg}"
            )
            return None

    async def remove_default_routes(self):
        """
        Removes the default route for the interface. Primarily used if you used add_default_route for the interface.
        @return: None
        """

        # Get existing routes for this adapter
        routes: list[dict[str, Any]] = (await run_command_async(  # type: ignore
            ["ip", "--json", "route"]
        )).output_from_json()
        for route in routes:
            if route["dev"] == self.name and route["dst"] == "default":
                await run_command_async(["ip", "route", "del", "default", "dev", self.name])


    async def add_default_route(self,
        router_address: Optional[str] = None,
        metric: Optional[int] = None,
    ) -> str:
        """
        Adds a default route to an interface
        @param router_address: Optionally specify which IP this route is via. If left blank, it will be grabbed from the dhclient lease file.
        @param metric: Optional metric for the route. If left as none, a lowest-priority metric starting at 200 will be calculated unless there are no other default routes.
        @return: A string representing the new default route.
        """
        interface=self.name

        # Obtain the router address if not manually provided
        if router_address is None:
            with open(f"/var/lib/dhcp/dhclient.{interface}.leases", "r") as lease_file:
                lease_data = lease_file.readlines()
                router_address = (
                    next((s for s in lease_data if "option routers" in s))
                    .strip()
                    .strip(";")
                    .split(" ", 2)[-1]
                )

        # Calculate a new metric if needed
        if metric is None:
            routes: list[dict[str, Any]] = (await run_command_async(  # type: ignore
                ["ip", "--json", "route"]
            )).output_from_json()
            default_routes = [x.get("metric", 0) for x in routes if x["dst"] == "default"]
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
        return new_route


    def blocking_scan(self):
        scan_results = self.interface.scan(block=True)
        for bss in scan_results:
            print(bss.get_ssid())


    def remove_all_networks(self):
        self.logger.info(f"Removing all networks from {self.name}")

        for network in self.interface.get_networks():
            self.interface.remove_network(network.get_path())

    async def connect(self, ssid:str, psk:Optional[str]=None, key_mgmt:str="WPA-PSK", proto:str="WPA2",timeout:float=20):
        self.logger.info(f"Connecting {self.name} to {ssid}")
        add_network_future = self.event_loop.create_future()
        signal = None
        states = []
        def prop_change_callback(result):
            self.logger.debug(f"{self.name}: {result}")
            if "State" in result:
                states.append(result)
                if result["State"] == "completed":
                    self.logger.debug(f"Connection to {ssid} completed")
                    add_network_future.set_result(states)
            if "DisconnectReason" in result:
                if result["DisconnectReason"] == 15:
                    self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
                    add_network_future.set_exception(WifiInterfaceAuthenticationError(f"An authentication error occurred: {states}"))
                if result["DisconnectReason"] == 13:
                    self.logger.debug(f"Disconnecting: {result['DisconnectReason']}")
                    add_network_future.set_exception(WifiInterfaceDisconnectedError(f"A disconnection occurred: {states}"))

        self.remove_all_networks()

        net_cfg = {
            "ssid": ssid,
            # "scan_ssid": 1,
            # "disabled":0,
            "ieee80211w": 0 # Default to no protected mgmt frames
        }
        if psk:
            net_cfg["psk"] = psk
            net_cfg["key_mgmt"] = key_mgmt
            net_cfg["proto"] = proto

        self.ssid = ssid
        self.psk = psk


        signal = self.interface.register_signal('PropertiesChanged', prop_change_callback)
        add_res = self.interface.add_network(net_cfg)
        new_net = self.interface.get_networks()[0]
        self.interface.select_network(new_net.get_path())

        # PropertiesChanged
        try:
            return await asyncio.wait_for(asyncio.shield(add_network_future), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError) as e:
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
        # self.reactor.install()
        self.reactor_thread = threading.Thread(target=self.reactor.run, kwargs={'installSignalHandlers': 0})
        self.reactor_thread.start()
        self.reactor._justStopped = False
        # Let the reactor start
        time.sleep(0.1)
        self.current_adapter_config = {}

        # Start Driver
        self.driver = WpaSupplicantDriver(self.reactor)

        # Connect to the supplicant, which returns the "root" D-Bus object for wpa_supplicant
        self.supplicant = self.driver.connect()

        self.interfaces = {}

    def __del__(self):
        self.reactor.stop()
        self.reactor_thread.join(timeout=4)

    def get_or_create_interface(self, interface_name):


        if interface_name not in self.interfaces:
            try:
                self.interfaces[interface_name] = WifiInterface(interface_name, self.supplicant, self.supplicant.create_interface(interface_name), event_loop=self.event_loop)
            except wpa_supplicant.core.InterfaceExists as e:
                self.logger.info(f"Interface {interface_name} already exists; adding to list.")
                self.interfaces[interface_name] = WifiInterface(interface_name, self.supplicant, self.supplicant.get_interface(interface_name), event_loop=self.event_loop)

        return self.interfaces[interface_name]


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

    async def main():
        wc = WiFiControlWpaSupplicant()

        wlan_if = wc.get_or_create_interface("wlan0")
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
        pprint(wlan_if.interface.get_current_network())

        print("Done")

        del wc
    asyncio.get_event_loop().run_until_complete(main())