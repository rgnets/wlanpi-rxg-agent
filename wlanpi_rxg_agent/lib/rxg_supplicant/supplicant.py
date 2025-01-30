import asyncio
import json
import logging
import os
from typing import Optional

import wlanpi_rxg_agent.utils as utils

from requests import ConnectTimeout, ReadTimeout

from api_client import ApiClient
from certificate_tool import CertificateTool
from constants import CONFIG_DIR
from lib.configuration.agent_config_file import AgentConfigFile
from lib.event_bus import EventBus
from lib.domain import RxgAgentEvents
from lib.rxg_supplicant.domain import  Messages as RxgSupplicantMessages, RxgSupplicantEvents
from models.exceptions import RXGAgentException

from busses import command_bus,message_bus

from enum import Enum
from typing import Literal


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
            event_bus: EventBus,
            verify_ssl: bool = True,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        self.supplicant_state: RxgSupplicantState = RxgSupplicantState.UNASSOCIATED
        self.verify_ssl = verify_ssl
        self.api_verify_ssl = False
        self.event_bus = event_bus

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
        os.chmod(self.cert_dir, 0o755)
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
        # self.current_ca = ""
        # self.current_cert = ""

        self.setup_listeners()


    def setup_listeners(self):
        self.event_bus.add_listener(RxgAgentEvents.STARTUP_COMPLETE, self.startup_complete_handler)
        self.event_bus.add_listener('agent_config_updated', self.reload_handler)

    async def startup_complete_handler(self, event):
        self.load_config()
        server_ip = self.find_rxg()
        await self.configure_server(server_ip=server_ip)

    async def reload_handler(self, event):
        # Emit commands to trigger connnection shutdowns for reload, or whatever is appropriate

        # For now, calling the startup handler should handle things just fine
        await self.startup_complete_handler(event)



    def load_config(self) -> None:
        """
        Loads configuration from the defined config file
        """
        # self.logger.info(f"Loading config file from {self.bridge_config_file.config_file}")
        # async with self.agent_config_lock:
        self.agent_config_file.load_or_create_defaults(allow_empty=False)
        self.override_server = self.agent_config_file.data.get('General').get("override_rxg", None)
        self.fallback_server = self.agent_config_file.data.get('General').get("fallback_rxg", None)


    def test_address_for_rxg(self, ip: str) -> bool:
        """
        Checks that the expected WLAN Pi control node on an rXg is present and
        responsive on an IP address, which would indicate that it's a viable
        controller.
        """
        api_client = ApiClient(verify_ssl=self.api_verify_ssl, timeout=5)

        try:
            resp = api_client.check_device(ip)

        except (ConnectTimeout, ConnectionError, ReadTimeout) as e:
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

    def find_rxg(self, max_hops=3):
        # Check if an override server is configured, validate and use it if so.
        if self.override_server and self.test_address_for_rxg(self.override_server):
            return self.override_server

        first_gateway = utils.get_default_gateways().get("eth0", None)

        if not first_gateway:
            raise RXGAgentException("Unable to find first gateway on eth0")

        if self.test_address_for_rxg(first_gateway):
            return first_gateway

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
            if i < max_hops and self.test_address_for_rxg(address):
                return address

        # Todo: insert fallback here
        if self.fallback_server and self.test_address_for_rxg(self.fallback_server):
            return self.fallback_server

        raise RXGAgentException("Unable to find an rXg.")

    def get_client_cert(self, server_ip):
        api_client = ApiClient(verify_ssl=self.api_verify_ssl, server_ip=server_ip)
        get_cert_resp = api_client.get_cert()
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


    async def check_registration(self, server_ip:str):
        api_client = ApiClient(server_ip=server_ip, verify_ssl=self.api_verify_ssl)
        self.logger.debug(f"Checking if we need to register with {api_client.ip}")
        resp = api_client.check_device()
        if resp.status_code == 200:
            response_data = resp.json()
            return response_data["status"] != "unregistered"
        # TODO: DO we need to do anything else here? Raise on non-200?


    async def register_with_server(self, server_ip: str):
        api_client = ApiClient(server_ip=server_ip, verify_ssl=self.api_verify_ssl)
        # self.event_bus.emit(RxgSupplicantEvents.REGISTERING, server_ip)
        # self.supplicant_state = RxgSupplicantState.REGISTERING

        registration_resp = api_client.register(
            model=utils.get_model_info()["Model"], csr=self.csr
        )

        if registration_resp.status_code == 200:
            self.logger.info(
                f"Successfully registered with {self.active_server}"
            )
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


    def renew_client_cert(self, server_ip):
        get_cert_success, status, ca_str, cert_str, host, port = self.get_client_cert(
            server_ip=server_ip
        )
        if get_cert_success:
            if not status == "approved":
                self.logger.warning(
                    "Server has not approved registration yet."
                )
                return False
            if not cert_str:
                self.logger.warning(
                    "Server has not provided a certificate."
                )
                return False

            # TODO: Emit this data for use by other parts of the system.
            # self.current_cert = cert_str
            self.cert_tool.save_cert(cert_str)
            # self.current_ca = ca_str
            self.cert_tool.save_ca(ca_str)
            # if host is not None:
            #     self.active_server = host
            # self.active_port = port
            return True
        return False


    # async def handle_registration(self, server_ip: Optional[str] = None) -> bool:
    async def configure_server(self, server_ip: str) -> bool:
        try:
            registered = await self.check_registration(server_ip=server_ip)
            if registered:
                self.supplicant_state = RxgSupplicantState.REGISTERED
                self.event_bus.emit(RxgSupplicantEvents.REGISTERED, server_ip)
            else:
                self.supplicant_state = RxgSupplicantState.UNREGISTERED
                self.event_bus.emit(RxgSupplicantEvents.UNREGISTERED, server_ip)

                self.logger.info(f"Not registered with {server_ip}. Registering...")
                # Reinitialize the certificate tool with the active server
                self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
                self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
                self.event_bus.emit(RxgSupplicantEvents.REGISTERING, server_ip)
                registered = await self.register_with_server(server_ip=server_ip)

            # By now, the client should be registered. If not, we're waiting for a successful attempt.
            # Attempt to get our cert and CA
            if registered:
                self.event_bus.emit(RxgSupplicantEvents.REGISTERED, server_ip)
                self.supplicant_state = RxgSupplicantState.REGISTERED
                self.logger.debug(
                    f"Registered with {server_ip}. Attempting to get cert info."
                )
                # self.supplicant_state = RxgSupplicantState.CERTIFYING
                self.event_bus.emit(RxgSupplicantEvents.CERTIFYING, server_ip)
                cert_result = self.renew_client_cert(server_ip=server_ip)
                if cert_result:
                    self.supplicant_state = RxgSupplicantState.CERTIFIED
                    self.event_bus.emit(RxgSupplicantEvents.CERTIFIED, server_ip)
                    return True
                else:
                    self.event_bus.emit(RxgSupplicantEvents.CERTIFICATION_FAILED, server_ip)
                    return False
            else:
                self.event_bus.emit(RxgSupplicantEvents.REGISTRATION_FAILED, server_ip)
                return False
            return False
        except (ConnectTimeout, ConnectionError) as e:
            self.logger.warning(f"Configuring {self.active_server} failed: {e}")
            self.event_bus.emit(RxgSupplicantEvents.ERROR, e)
            return False


# if __name__ == "__main__":
#     supp = RxgSupplicant()
#     # supp.fallback_server = "192.168.20.81"
#     res = supp.find_rxg()
#     print(res)