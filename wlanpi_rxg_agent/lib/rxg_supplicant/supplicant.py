import asyncio
import json
import logging
import os
from enum import Enum
from typing import Literal, Optional

from requests import ConnectTimeout, ReadTimeout

import wlanpi_rxg_agent.lib.domain as agent_domain
import wlanpi_rxg_agent.lib.rxg_supplicant.domain as supplicant_domain
import wlanpi_rxg_agent.utils as utils
from wlanpi_rxg_agent.api_client import ApiClient
from wlanpi_rxg_agent.busses import command_bus, message_bus
from wlanpi_rxg_agent.certificate_tool import CertificateTool
from wlanpi_rxg_agent.constants import CONFIG_DIR
from wlanpi_rxg_agent.lib.configuration.agent_config_file import AgentConfigFile
from wlanpi_rxg_agent.models.exceptions import RXGAgentException
from wlanpi_rxg_agent.structures import FlatResponse


class RxgSupplicantState(Enum):
    UNASSOCIATED = 0
    UNREGISTERED = 1
    REGISTERING = 2
    REGISTERED = 3
    CERTIFIED = 4
    MONITORING = 5


class RxgSupplicant:

    def __init__(
        self,
        verify_ssl: bool = True,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        self.supplicant_state: RxgSupplicantState = RxgSupplicantState.UNASSOCIATED
        self.verify_ssl = verify_ssl
        self.api_verify_ssl = False

        # Config Files
        self.agent_config_file = AgentConfigFile()
        self.agent_config_file.load_or_create_defaults()
        self.agent_config_lock = asyncio.Lock()
        #

        self.new_server: Optional[str] = None

        self.override_server: Optional[str] = None
        self.fallback_server: Optional[str] = None
        self.active_server: Optional[str] = None
        # self.new_server: Optional[str] = None

        # Initialize certificates
        self.cert_dir = os.path.join(CONFIG_DIR, "certs")
        os.makedirs(self.cert_dir, exist_ok=True)
        os.chmod(self.cert_dir, 0o700)
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
        # self.current_ca = ""
        # self.current_cert = ""

        self.last_certified_connection: Optional[
            supplicant_domain.Messages.NewCertifiedConnection
        ] = None

        self.setup_listeners()

    def setup_listeners(self):
        self.logger.info("Setting up listeners")
        message_bus.add_handler(
            agent_domain.Messages.StartupComplete, self.startup_complete_handler
        )
        message_bus.add_handler(
            agent_domain.Messages.AgentConfigUpdated, self.reload_handler
        )
        message_bus.add_handler(
            agent_domain.Messages.AgentConfigUpdate, self.config_update_handler
        )
        message_bus.add_handler(
            supplicant_domain.Messages.Certified, self.re_emit_certified_if_new
        )

    async def re_emit_certified_if_new(
        self, event: supplicant_domain.Messages.Certified
    ):
        self.logger.debug("Checking if we need to re-emit certified connection")
        if event != self.last_certified_connection:
            self.logger.debug("re-emitting certified connection...")
            self.last_certified_connection = event
            message_bus.handle(
                supplicant_domain.Messages.NewCertifiedConnection(**event.__dict__)
            )

    async def startup_complete_handler(self, event):
        await self.load_config()

        while True:
            try:
                server_ip = await self.find_rxg()
                res = await self.configure_server(server_ip=server_ip)
                if not res:
                    raise RXGAgentException("Unable to configure server.")
                self.active_server = server_ip
                break
            # Generally, catching "Exception" is bad. However, this is *not* allowed to die
            # or else we lose contact with the agent.
            except Exception as e:
                msg = "Error finding rXg Waiting 10 seconds and trying again. "
                self.logger.warning(msg, exc_info=True)
                message_bus.handle(supplicant_domain.Messages.Error(msg, e))
                await asyncio.sleep(10)
        await asyncio.sleep(30)
        asyncio.create_task(self.monitor_for_new_rxg(), name="monitor_for_new_rxg")

    async def monitor_for_new_rxg(self, wait_period=60):
        while True:
            try:
                server_ip = await self.find_rxg()
                res = await self.configure_server(server_ip=server_ip)
                if not res:
                    raise RXGAgentException("Unable to configure server.")
                self.active_server = server_ip
            # Generally, catching "Exception" is bad. However, this is *not* allowed to die
            # or else we lose contact with the agent.
            except Exception as e:
                msg = "Error finding rXg Waiting 10 seconds and trying again. "
                self.logger.warning(msg, exc_info=True)
                message_bus.handle(supplicant_domain.Messages.Error(msg, e))
            await asyncio.sleep(wait_period)

    async def reload_handler(self, event):
        # Emit commands to trigger connection shutdowns for reload, or whatever is appropriate

        # For now, calling the startup handler should handle things just fine
        await self.startup_complete_handler(event)

    async def config_update_handler(
        self, update: agent_domain.Messages.AgentConfigUpdate
    ) -> None:
        """
        Updates the configuration and emits any necessary signals afterwards
        :param update:agent_domain.Messages.AgentConfigUpdate
        :return: None
        """

        changed = False
        async with self.agent_config_lock:
            if update.safe:
                if update.fallback_rxg is not None:
                    if self.fallback_server != update.fallback_rxg:
                        changed = True
                    if not len(update.fallback_rxg):
                        update.fallback_rxg = None
                    elif await self.test_address_for_rxg(update.fallback_rxg):
                        self.fallback_server = update.fallback_rxg
                if update.override_rxg is not None:
                    if self.override_server != update.override_rxg:
                        changed = True
                    if not len(update.override_rxg):
                        update.override_rxg = None
                    elif await self.test_address_for_rxg(update.override_rxg):
                        self.override_server = update.override_rxg

            else:
                if update.fallback_rxg is not None:
                    if self.fallback_server != update.fallback_rxg:
                        changed = True
                    if len(update.fallback_rxg):
                        self.fallback_server = update.fallback_rxg
                    else:
                        update.fallback_rxg = None
                if update.override_rxg is not None:
                    if self.override_server != update.override_rxg:
                        changed = True
                    if len(update.override_rxg):
                        self.override_server = update.override_rxg
                    else:
                        update.override_rxg = None

            if changed:
                await self.save_config()
        if changed:
            message_bus.handle(agent_domain.Messages.AgentConfigUpdated)

    async def load_config(self) -> None:
        """
        Loads configuration from the defined config file
        """
        # self.logger.info(f"Loading config file from {self.bridge_config_file.config_file}")
        async with self.agent_config_lock:
            self.agent_config_file.load_or_create_defaults(allow_empty=False)
            self.override_server = self.agent_config_file.data.get("General").get(
                "override_rxg", None
            )
            self.fallback_server = self.agent_config_file.data.get("General").get(
                "fallback_rxg", None
            )

    async def save_config(self) -> None:
        async with self.agent_config_lock:
            # if "override_rxg" in new_config:
            #     self.override_server = new_config["override_rxg"]
            # if "fallback_rxg" in new_config:
            #     self.fallback_server = new_config["fallback_rxg"]
            self.agent_config_file.data["General"][
                "override_rxg"
            ] = self.override_server
            self.agent_config_file.data["General"][
                "fallback_rxg"
            ] = self.fallback_server
            self.agent_config_file.save()

    async def test_address_for_rxg(self, ip: str) -> bool:
        """
        Checks that the expected WLAN Pi control node on an rXg is present and
        responsive on an IP address, which would indicate that it's a viable
        controller.
        """
        api_client = ApiClient(verify_ssl=self.api_verify_ssl, timeout=5)

        try:
            resp = await api_client.check_device(ip)

        except (
            ConnectTimeout,
            ConnectionError,
            ReadTimeout,
            asyncio.TimeoutError,
        ) as e:
            self.logger.warning(f"Testing of address {ip} failed: {e}")
            return False

        if resp.status_code == 200:
            try:
                data = resp.json()  # Try to parse the JSON
            except json.JSONDecodeError:
                return False
            else:
                if "status" in data.keys():
                    return True
        return False

    async def find_rxg(self, max_hops=3):
        # Check if an override server is configured, validate and use it if so.
        if self.override_server and await self.test_address_for_rxg(
            self.override_server
        ):
            self.logger.info(
                f"Override server {self.override_server} is valid. Using it."
            )
            return self.override_server
        self.logger.debug(
            "No valid override server configured. Checking default routes. Starting with first gateway on eth0."
        )
        first_gateway = utils.get_default_gateways().get("eth0", None)

        if not first_gateway:
            raise RXGAgentException("Unable to find first gateway on eth0")

        self.logger.debug(f"First gateway on eth0: {first_gateway}")
        if await self.test_address_for_rxg(first_gateway):
            self.logger.debug(f"First gateway on eth0 is a valid rXg: {first_gateway}")
            return first_gateway

        self.logger.debug(
            "First gateway on eth0 is not a valid rXg. Looking for a valid rXg on a route to google.com."
        )
        raw_hop_data: list[dict] = utils.trace_route("google.com")["hops"]
        filtered_hops: list[dict] = list(
            filter(lambda e: len(e["probes"]), raw_hop_data)
        )

        # pp(filtered_hops)
        hop_addresses = [
            x["probes"][0]["ip"]
            for x in sorted(filtered_hops, key=lambda hop: hop["hop"])
        ]

        for i, address in enumerate(hop_addresses):
            self.logger.debug(f"Checking address {address} for rXg")
            if i < max_hops and await self.test_address_for_rxg(address):
                self.logger.debug(f"Address {address} is a valid rXg")
                return address

        self.logger.debug(
            "No valid rXg found. Checking for configured fallback server."
        )
        # Todo: insert fallback here
        if self.fallback_server and await self.test_address_for_rxg(
            self.fallback_server
        ):
            self.logger.debug("Fallback server is valid. Using it.")
            return self.fallback_server
        self.logger.error("Unable find a valid rXg. Throwing in the towel.")
        raise RXGAgentException("Unable to find an rXg.")

    async def get_client_cert(self, server_ip):
        api_client = ApiClient(verify_ssl=self.api_verify_ssl, server_ip=server_ip)
        get_cert_resp = await api_client.get_cert()
        if get_cert_resp.status_code == 200:
            # Registration has succeeded, we need to get our certs.
            response_data = get_cert_resp.json()
            self.logger.debug(f"Get Cert Response: {json.dumps(response_data)}")

            return (
                True,
                response_data["status"],
                response_data["ca"],
                response_data["certificate"],
                response_data.get("host"),
                response_data["port"],
            )
        else:
            self.logger.warning(
                f"get_client_cert failed: {get_cert_resp.status_code}: {get_cert_resp.reason} "
            )
            return False, None, None, None, None, None

    async def check_registration(self, server_ip: str):
        api_client = ApiClient(server_ip=server_ip, verify_ssl=self.api_verify_ssl)
        self.logger.info(f"Checking if we need to register with {api_client.ip}")
        resp = await api_client.check_device()
        if resp.status_code == 200:
            response_data = resp.json()
            return response_data["status"] != "unregistered"
        else:
            self.logger.warning(
                f"check_registration failed: {resp.status_code}: {resp.reason}"
            )
            return False
        # TODO: DO we need to do anything else here? Raise on non-200?

    async def register_with_server(self, server_ip: str):
        api_client = ApiClient(server_ip=server_ip, verify_ssl=self.api_verify_ssl)
        # self.event_bus.emit(RxgSupplicantEvents.REGISTERING, server_ip)
        # self.supplicant_state = RxgSupplicantState.REGISTERING

        registration_resp: FlatResponse = await api_client.register(
            model=utils.get_model_info()["Model"], csr=self.csr
        )

        if registration_resp.status_code == 200:
            self.logger.info(f"Successfully registered with {self.active_server}")
            # self.event_bus.emit(RxgSupplicantEvents.REGISTERED, server_ip)
            # self.supplicant_state = RxgSupplicantState.REGISTERED
            return True
        else:
            # If registration failed here due to a non-200 status code, there's not much
            # the client can do except wait and try again later
            self.logger.error(
                f"Registration failed. Server said: {registration_resp.status_code}:"
                f" {registration_resp.content}"
            )
            # self.event_bus.emit(RxgSupplicantEvents.REGISTRATION_FAILED, server_ip)

            # self.supplicant_state = RxgSupplicantState.UNREGISTERED
            # self.event_bus.emit(RxgSupplicantEvents.UNREGISTERED, None)
            return False

    async def renew_client_cert(
        self, server_ip
    ) -> tuple[bool, Optional[supplicant_domain.Messages.Certified]]:
        self.logger.info("Renewing client cert")
        get_cert_success, status, ca_str, cert_str, host, port = (
            await self.get_client_cert(server_ip=server_ip)
        )
        if get_cert_success:
            if not status == "approved":
                self.logger.warning("Server has not approved registration yet.")
                return False, None
            if not cert_str:
                self.logger.warning("Server has not provided a certificate.")
                return False, None

            # TODO: Emit this data for use by other parts of the system.
            # self.current_cert = cert_str
            self.cert_tool.save_cert(cert_str)
            # self.current_ca = ca_str
            self.cert_tool.save_ca(ca_str)
            # if host is not None:
            #     self.active_server = host
            # self.active_port = port
            self.logger.info("Server has certified us")
            return True, supplicant_domain.Messages.Certified(
                host=host,
                port=port,
                ca=ca_str,
                certificate=cert_str,
                status=status,
                ca_file=self.cert_tool.ca_file,
                certificate_file=self.cert_tool.cert_file,
                key_file=self.cert_tool.key_file,
                cert_reqs=2,
            )
        return False, None

    # async def handle_registration(self, server_ip: Optional[str] = None) -> bool:
    async def configure_server(self, server_ip: str) -> bool:
        try:
            registered = await self.check_registration(server_ip=server_ip)
            if registered:
                self.supplicant_state = RxgSupplicantState.REGISTERED
                message_bus.handle(supplicant_domain.Messages.Registered())
            else:
                self.supplicant_state = RxgSupplicantState.UNREGISTERED
                message_bus.handle(supplicant_domain.Messages.Unregistered())

                self.logger.info(f"Not registered with {server_ip}. Registering...")
                # Reinitialize the certificate tool with the active server
                self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
                self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
                message_bus.handle(supplicant_domain.Messages.Registering())
                registered = await self.register_with_server(server_ip=server_ip)

            # By now, the client should be registered. If not, we're waiting for a successful attempt.
            # Attempt to get our cert and CA
            if registered:
                message_bus.handle(supplicant_domain.Messages.Registered())
                self.supplicant_state = RxgSupplicantState.REGISTERED
                self.logger.info(
                    f"Registered with {server_ip}. Attempting to get cert info."
                )
                # self.supplicant_state = RxgSupplicantState.CERTIFYING
                message_bus.handle(supplicant_domain.Messages.Certifying())
                cert_result, certified = await self.renew_client_cert(
                    server_ip=server_ip
                )
                if cert_result:
                    self.supplicant_state = RxgSupplicantState.CERTIFIED
                    if certified:
                        self.logger.info(f"Certified with {server_ip}. Dispatching")
                        message_bus.handle(certified)
                    return True
                else:
                    message_bus.handle(supplicant_domain.Messages.CertificationFailed())
                    return False
            else:
                message_bus.handle(supplicant_domain.Messages.RegistrationFailed())
                return False
            return False
        except (ConnectTimeout, ConnectionError, asyncio.TimeoutError) as e:
            self.logger.warning(f"Configuring {self.active_server} failed: {e}")
            message_bus.handle(supplicant_domain.Messages.Error(e))
            return False


if __name__ == "__main__":

    async def main():
        supp = RxgSupplicant(verify_ssl=False)
        # supp.fallback_server = "192.168.20.81"
        # res = await supp.find_rxg()
        res = await supp.test_address_for_rxg("gcr.rxgs.ketchel.xyz")
        print(res)

    asyncio.get_event_loop().run_until_complete(main())
