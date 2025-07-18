import logging
import os
import random
import string
import typing as t
from json import JSONDecodeError

import wlanpi_rxg_agent.lib.agent_actions.domain as actions_domain
import wlanpi_rxg_agent.lib.domain as agent_domain
import wlanpi_rxg_agent.lib.network_control.domain as network_control_domain
import wlanpi_rxg_agent.lib.rxg_supplicant.domain as supplicant_domain
import wlanpi_rxg_agent.lib.wifi_control.domain as wifi_domain
import wlanpi_rxg_agent.utils as utils
from wlanpi_rxg_agent.api_client import ApiClient
from wlanpi_rxg_agent.busses import command_bus, message_bus
from wlanpi_rxg_agent.core_client import CoreClient
from wlanpi_rxg_agent.kismet_control import KismetControl
from wlanpi_rxg_agent.lib.configuration.bootloader_config_file import (
    BootloaderConfigFile,
)
from wlanpi_rxg_agent.lib.sip_control.sip_test_baresip import SipTestBaresip


class AgentActions:

    def __init__(
        self,
        wlan_pi_core_base_url: str = "http://127.0.0.1:31415",
        kismet_base_url: str = "http://127.0.0.1:2501",
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.bootloader_config = BootloaderConfigFile()

        # Core
        self.core_base_url = wlan_pi_core_base_url
        self.core_client = CoreClient(base_url=self.core_base_url)
        # Kismet
        self.kismet_base_url = kismet_base_url
        self.kismet_control = KismetControl()

        # Event/Command Bus
        self.setup_listeners()

    def setup_listeners(self):
        self.logger.info("Setting up listeners")
        # TODO: Surely we can implement this as some sort of decorator function?
        pairs = (
            (actions_domain.Commands.SetRxgs, self.set_rxgs),
            (actions_domain.Commands.SetCredentials, self.set_password),
            (actions_domain.Commands.Reboot, self.reboot),
            (actions_domain.Commands.ConfigureAgent, self.configure_agent),
            (actions_domain.Commands.ConfigureRadios, self.configure_radios),
            (actions_domain.Commands.GetClients, self.exec_get_clients),
            (actions_domain.Commands.Ping, self.run_ping_test),
            (actions_domain.Commands.Traceroute, self.run_traceroute),
            (actions_domain.Commands.Dig, self.run_dig_test),
            (actions_domain.Commands.DhcpTest, self.run_dhcp_test),
            (actions_domain.Commands.TCPDump, self.handle_tcp_dump_on_interface),
            (actions_domain.Commands.Iperf2, self.run_iperf2),
            (actions_domain.Commands.Iperf3, self.run_iperf3),
            (actions_domain.Commands.SipTest, self.run_sip_test),
        )

        for command, handler in pairs:
            command_bus.add_handler(command, handler)

    async def reboot(self):
        self.logger.info(f"Rebooting")
        return utils.run_command("reboot", raise_on_fail=False)

    async def set_rxgs(self, data: actions_domain.Commands.SetRxgs):
        self.bootloader_config.load()

        if data.override is not None:
            self.logger.info(f"Setting override_rxg: {data.override}")
            self.bootloader_config.data["boot_server_override"] = data.override

        if data.fallback is not None:
            self.logger.info(f"Setting fallback_rxg: {data.fallback}")
            self.bootloader_config.data["boot_server_fallback"] = data.fallback
        self.bootloader_config.save()
        message_bus.handle(
            agent_domain.Messages.AgentConfigUpdate(
                override_rxg=data.override, fallback_rxg=data.fallback
            )
        )
        # if self.agent_reconfig_callback is not None:
        #     await self.agent_reconfig_callback({"override_rxg": value})
        return self.bootloader_config.data

    async def set_password(self, event: actions_domain.Commands.SetCredentials):
        self.logger.info(f"Setting new password.")
        return await utils.run_command_async(
            "chpasswd", input=f"{event.user}:{event.password}"
        )

    async def configure_agent(self, event: actions_domain.Commands.ConfigureAgent):
        self.logger.info(
            f"Configuring agent: {event}",
        )

        # Configure Radios first
        # await command_bus.handle(actions_domain.Commands.ConfigureRadios(interfaces=event.wifi))
        command_bus.handle(
            actions_domain.Commands.ConfigureRadios(interfaces=event.wifi)
        )

        # Then ping targets
        command_bus.handle(
            actions_domain.Commands.ConfigurePingTargets(targets=event.ping_targets)
        )
        # Then traceroute targets
        command_bus.handle(
            actions_domain.Commands.ConfigureTraceroutes(
                targets=event.traceroute_targets
            )
        )
        # Then Speed Tests
        command_bus.handle(
            actions_domain.Commands.ConfigureSpeedTests(targets=event.speed_tests)
        )
        # Then Sip Tests
        command_bus.handle(
            actions_domain.Commands.ConfigureSipTests(targets=event.sip_tests)
        )

    async def configure_radios(self, event: actions_domain.Commands.ConfigureRadios):
        self.logger.info(f"Configuring radios: New payload: {event}")
        for interface_name, config in event.interfaces.items():
            # if not interface_name in self.kismet_control.available_kismet_interfaces().keys():
            #     return MQTTResponse(
            #         status="validation_error",
            #         errors=[
            #             [
            #                 "RxgMqttClient.configure_radios",
            #                 f"Interface '{interface_name}' is not available",
            #             ]
            #         ],
            #     )
            new_mode = config.mode
            if new_mode == "monitor":
                self.logger.debug(f"{interface_name} should be in monitor mode.")
                if not self.kismet_control.is_kismet_running():
                    self.logger.debug(f"Starting kismet on {interface_name}mon")
                    self.kismet_control.start_kismet(interface_name)
                else:
                    if (
                        interface_name
                        not in self.kismet_control.all_kismet_sources().keys()
                    ):
                        self.logger.debug(f"Adding {interface_name}")
                        self.kismet_control.add_source(interface_name)
                    if (
                        interface_name
                        not in self.kismet_control.active_kismet_interfaces().keys()
                    ):
                        self.logger.debug(f"Enabling {interface_name}mon")
                        self.kismet_control.open_source_by_name(interface_name)
                        self.kismet_control.resume_source_by_name(interface_name)
            else:
                self.logger.debug(f"{interface_name} should be in {new_mode} mode.")
                # Teardown kismet monitor control
                if (
                    self.kismet_control.is_kismet_running()
                    and interface_name
                    in self.kismet_control.active_kismet_interfaces().keys()
                ):
                    self.kismet_control.close_source_by_name(interface_name)
                await utils.run_command_async(
                    ["iw", "dev", interface_name + "mon", "del"], raise_on_fail=False
                )
                await utils.run_command_async(
                    ["ip", "link", "set", interface_name, "up"]
                )
                # TODO: Do full adapter config here.

                wlan_if = command_bus.handle(
                    wifi_domain.Commands.GetOrCreateInterface(if_name=interface_name)
                )
                # wlan_if = self.wifi_control.get_or_create_interface(interface_name=interface_name)
                self.logger.info(f"Checking managed state of {interface_name}")
                wlan_data = config.wlan
                if wlan_data is None:
                    self.logger.info(f"{interface_name} should be disconnected.")
                    if wlan_if.connected:
                        self.logger.info(
                            f"{interface_name} is connected to a network. Disconnecting."
                        )
                        wlan_if.disconnect()
                else:
                    if isinstance(wlan_data, list):
                        wlan_data = wlan_data[0]
                    self.logger.info(
                        f"{interface_name} should be connected to {wlan_data.ssid}. (Auth hidden) Currently connected to {wlan_if.ssid}"
                    )
                    if not (
                        wlan_if.connected
                        and wlan_if.ssid == wlan_data.ssid
                        and wlan_if.psk == wlan_data.psk
                    ):
                        self.logger.info(
                            f"Connection state of {interface_name} is incorrect. Reconnecting."
                        )

                        try:
                            await wlan_if.connect(
                                ssid=wlan_data.ssid, psk=wlan_data.psk
                            )
                            self.logger.info(
                                f"Connection to {wlan_data.ssid} completed. DHCP and routing will be handled automatically by NetworkControlManager."
                            )
                            # Note: DHCP renewal and route configuration are now handled automatically
                            # by NetworkControlManager when it detects the interface IP change via netlink events
                        except TimeoutError:
                            self.logger.error(
                                f"Connection to {wlan_data.ssid} timed out."
                            )

        if (
            self.kismet_control.is_kismet_running()
            and len(self.kismet_control.active_kismet_interfaces()) == 0
        ):
            self.logger.info("No monitor interfaces. Killing kismet.")
            self.kismet_control.kill_kismet()
        return (await utils.run_command_async(["iwconfig"], raise_on_fail=False)).stdout

    async def exec_get_clients(self, client):
        if self.kismet_control.is_kismet_running():
            return self.kismet_control.get_seen_devices()
        else:
            return self.kismet_control.empty_seen_devices()

    async def handle_tcp_dump_on_interface(
        self, event: actions_domain.Commands.TCPDump
    ):
        result = await self.tcpdump_on_interface(
            interface_name=event.interface,
            upload_ip=event.upload_ip,
            upload_token=event.upload_token,
            max_packets=event.max_packets,
            timeout=event.timeout,
            filter=event.filter,
        )
        return result

    async def tcpdump_on_interface(
        self,
        interface_name,
        upload_ip: str,
        upload_token: str,
        filter: t.Optional[str],
        max_packets: t.Optional[int] = None,
        timeout: t.Optional[int] = None,
    ) -> str:
        self.logger.info(f"Starting tcpdump on interface {interface_name}")

        if timeout is None and max_packets is None:
            # Forcibly set a 1-minute timeout if no timeout is provided.
            timeout = 60

        # Query kismet control to see if the interface is one it has active, if so, append "mon"
        if (
            self.kismet_control.is_kismet_running()
            and interface_name in self.kismet_control.active_kismet_interfaces().keys()
            and not interface_name.endswith("mon")
        ):
            interface_name += "mon"

        random_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        filepath = f"/tmp/{random_str}.pcap"

        cmd = ["tcpdump", "-i", interface_name, "-w", filepath]

        if max_packets:
            cmd.extend(["-c", str(max_packets)])
        if timeout:
            cmd = ["timeout", "--preserve-status", str(timeout)] + cmd
        if filter:
            cmd.extend(filter.split(" "))

        result = ""
        try:
            self.logger.info(f"Starting tcpdump with command: {' '.join(cmd)}")
            c_res = await utils.run_command_async(cmd, use_shlex=False)
            result = c_res.stdout + c_res.stderr
            self.logger.info(f"Finished tcpdump on interface {interface_name}")

            api_client = ApiClient(server_ip=upload_ip, verify_ssl=False, timeout=None)
            # Then get a token and upload it
            self.logger.info(f"Uploading dump file to {api_client.ip}")
            ul_result = await api_client.upload_tcpdump(
                file_path=filepath, submit_token=upload_token
            )
            self.logger.info(
                f"Finished upload. Result: {ul_result.status_code} { ul_result.reason} {ul_result.text}"
            )
        finally:
            self.logger.info(f"Unlinking {filepath}")
            os.unlink(filepath)
        return result

    async def run_ping_test(
        self, event: actions_domain.Commands.Ping
    ) -> t.Union[actions_domain.Data.PingResult, actions_domain.Data.PingFailure]:
        self.logger.info(f"Running ping test: {event}")
        # TODO: Errors when no destination host are found are resolved in a newer version of the JC library. To fix this, core will need to include the new version instead of using the system version.
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/ping", data=event.model_dump()
        )
        try:
            res_data = res.json()
        except Exception as e:
            self.logger.exception(msg="Failure getting JSON result from Ping test")
            result_payload = actions_domain.Data.PingFailure(
                destination=event.host, message=str(e)
            )
        else:
            if "message" in res_data:
                result_payload = actions_domain.Data.PingFailure(**res_data)
            else:
                result_payload = actions_domain.Data.PingResult(**res_data)
        message_bus.handle(result_payload)
        # We don't emit the Test Complete version here since that requires an rXg identifier to be useful
        return result_payload

    async def run_iperf2(
        self, event: actions_domain.Commands.Iperf2
    ) -> actions_domain.Messages.Iperf2Result:
        self.logger.info(f"Running traceroute: {event}")
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/iperf2/client", data=event.model_dump()
        )
        result_payload = actions_domain.Messages.Iperf2Result(**res.json())
        message_bus.handle(result_payload)

        # We don't emit the Test Complete version here since that requires an rXg identifier to be useful
        return result_payload

    async def run_iperf3(
        self, event: actions_domain.Commands.Iperf3
    ) -> actions_domain.Messages.Iperf3Result:
        self.logger.info(f"Running traceroute: {event}")
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/iperf3/client", data=event.model_dump()
        )
        result_payload = actions_domain.Messages.Iperf3Result(**res.json())
        message_bus.handle(result_payload)
        # We don't emit the Test Complete version here since that requires an rXg identifier to be useful
        return result_payload

    async def run_traceroute(
        self, event: actions_domain.Commands.Traceroute
    ) -> actions_domain.Messages.TracerouteResponse:
        self.logger.info(f"Running traceroute: {event}")
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/traceroute", data=event.model_dump()
        )
        result_payload = actions_domain.Messages.TracerouteResponse(**res.json())
        message_bus.handle(result_payload)
        return result_payload

    async def run_dig_test(
        self, event: actions_domain.Commands.Dig
    ) -> actions_domain.Messages.DigTestComplete:
        self.logger.info(f"Running dig test: {event}")
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/dns/dig", data=event.model_dump()
        )

        res_json = res.json()
        if len(res_json) == 0:
            error = "No results returned from dig, probably a timeout."
        else:
            error = None
            result_payload = actions_domain.Messages.DigResponse(**res_json[0])
            message_bus.handle(result_payload)
        # Extra: emit a test complete message too, for now, since these don't have identifiable rXg models
        payload = actions_domain.Messages.DigTestComplete(
            error=error, request=event, result=res_json
        )
        message_bus.handle(payload)
        return payload

    async def run_dhcp_test(
        self, event: actions_domain.Commands.DhcpTest
    ) -> actions_domain.Messages.DhcpTestResponse:
        self.logger.info(f"Running dhcp test: {event}")
        res = await self.core_client.execute_async_request(
            "post", "api/v1/utils/dhcp/test", data=event.model_dump()
        )
        res_json = res.json()
        result_payload = actions_domain.Messages.DhcpTestResponse(**res_json)
        message_bus.handle(result_payload)
        # Extra: emit a test complete message too, for now, since these don't have identifiable rXg models
        message_bus.handle(
            actions_domain.Messages.DhcpTestComplete(request=event, result=res_json)
        )
        return result_payload

    async def run_sip_test(
        self, event: actions_domain.Commands.SipTest
    ) -> actions_domain.Messages.SipTestComplete:
        self.logger.info(f"Running sip test: {event}")
        route_added = False

        try:
            # 1. Setup temp directory and config
            conf_path = f"/tmp/bs_sip_test__{event.id}/"
            await SipTestBaresip.deploy_config(conf_path)

            # 2. Add host route for SIP server if a wireless interface is specified
            if event.interface:
                if event.interface.startswith("wlan"):
                    try:
                        self.logger.info(
                            f"Adding route to {event.sip_account.host} via {event.interface}"
                        )
                        route_main_result = await command_bus.handle(
                            network_control_domain.Commands.AddHostRoute(
                                host=event.sip_account.host, interface_name=event.interface, table_id=254
                            )
                        )

                        if not route_main_result.success:
                            self.logger.warning(
                                f"Failed to add route to {event.sip_account.host}: {route_main_result.error_message}"
                            )
                            # Continue with test but log the warning
                        else:
                            route_added = True
                            self.logger.info(
                                f"Added route to {route_main_result.resolved_ip} via {event.interface} main table"
                            )

                        route_result = await command_bus.handle(
                            network_control_domain.Commands.AddHostRoute(
                                host=event.sip_account.host, interface_name=event.interface
                            )
                        )

                        if not route_result.success:
                            self.logger.warning(
                                f"Failed to add route to {event.sip_account.host}: {route_result.error_message}"
                            )
                            # Continue with test but log the warning
                        else:
                            route_added = True
                            self.logger.info(
                                f"Added route to {route_result.resolved_ip} via {event.interface} dedicated table"
                            )

                    except Exception as e:
                        self.logger.warning(f"Error adding route for SIP test: {e}")
                        # Continue with test but log the error

            # 3. Execute SIP test
            sip_test = SipTestBaresip(
                gateway=event.sip_account.host,
                password=event.sip_account.auth_pass,
                user=event.sip_account.user,
                config_path=conf_path,
                debug=True,
                interface=event.interface,
            )

            sip_result = await sip_test.execute(
                callee=event.callee,
                post_connect=event.post_connect,
                call_timeout=event.call_timeout,
            )
            summary = actions_domain.Data.SipTestRtcpSummary.from_baresip_summary(
                sip_result
            )

            result_payload = actions_domain.Messages.SipTestComplete(
                request=event, result=summary
            )

        except Exception as e:
            self.logger.warning(f"SIP test failed: {e}", exc_info=True)
            result_payload = actions_domain.Messages.SipTestComplete(
                request=event, error=str(e)
            )

        finally:
            # 4. Cleanup route (always)
            if route_added and event.interface:
                try:
                    self.logger.info(
                        f"Removing route to {event.sip_account.host} via {event.interface}"
                    )

                    cleanup_main_result = await command_bus.handle(
                        network_control_domain.Commands.RemoveHostRoute(
                            host=event.sip_account.host, interface_name=event.interface, table_id=254
                        )
                    )

                    if not cleanup_main_result.success:
                        self.logger.warning(
                            f"Failed to remove route to {event.sip_account.host}: {cleanup_main_result.error_message}"
                        )
                    else:
                        self.logger.info(
                            f"Removed route to {event.sip_account.host} via {event.interface} main table"
                        )

                    cleanup_result = await command_bus.handle(
                        network_control_domain.Commands.RemoveHostRoute(
                            host=event.sip_account.host, interface_name=event.interface
                        )
                    )

                    if not cleanup_result.success:
                        self.logger.warning(
                            f"Failed to remove route to {event.sip_account.host}: {cleanup_result.error_message}"
                        )
                    else:
                        self.logger.info(
                            f"Removed route to {event.sip_account.host} via {event.interface} dedicated table"
                        )

                except Exception as e:
                    self.logger.error(f"Error during route cleanup: {e}")

        # 5. Publish results
        message_bus.handle(result_payload)
        return result_payload
