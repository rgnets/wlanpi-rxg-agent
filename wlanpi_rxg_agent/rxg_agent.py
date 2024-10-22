import json
import logging
import os
import time
from configparser import ConfigParser
from pprint import pp
from typing import Optional
from xxsubtype import bench
import dbus

import schedule

from requests import ConnectTimeout, ConnectionError
from urllib3.exceptions import MaxRetryError

import wlanpi_rxg_agent.utils as utils
from api_client import ApiClient
from certificate_tool import CertificateTool
from models.exceptions import RXGAgentException

logger = logging.getLogger(__name__)
# logging.basicConfig(filename='example.log', encoding='utf-8', level=logging.DEBUG)
logging.basicConfig(encoding="utf-8", level=logging.INFO)

CONFIG_DIR = "/etc/wlanpi-rxg-agent"
CONFIG_FILE = "/etc/wlanpi-rxg-agent/config.toml"

class RXGAgent:

    def __init__(
            self,
            verify_ssl:bool=True,
            config_path:str=CONFIG_FILE,

    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing RXGAgent")

        self.verify_ssl = verify_ssl
        self.config_path = config_path

        self.override_server: Optional[str] = None
        self.fallback_server: Optional[str] = None
        self.active_server: Optional[str] = None
        self.new_server: Optional[str] = None

        self.active_port: Optional[int] = None
        self.new_port: Optional[int] = None

        self.load_config()

        self.scheduled_jobs: list[schedule.Job] = []

        self.registered = False
        self.certification_complete = False

        self.api_client = ApiClient(verify_ssl=False)

        # Initialize certificates
        self.cert_dir = os.path.join(CONFIG_DIR,'certs')
        os.makedirs(self.cert_dir, exist_ok=True)
        os.chmod(self.cert_dir, 0o755)
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())



    def reinitialize_cert_tool(self, partner_id:Optional[str]=None):
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir, partner_id=partner_id)
        self.csr = self.cert_tool.get_csr_as_pem(node_name=utils.get_hostname())


    def load_config(self) -> None:
        """
        Loads configuration from the defined config file
        """
        self.logger.info(f"Loading config file from {self.config_path}")
        config = ConfigParser()
        if os.path.exists(self.config_path):
            config.read(self.config_path)
        else:
            self.logger.error(f"Cannot find config file! Check {self.config_path}")
            raise RXGAgentException(f"Cannot find config file! Check {self.config_path}")
        self.override_server = config.get("General", "override_rxg", fallback=None)
        self.fallback_server = config.get("General", "fallback_rxg", fallback=None)

    def test_address_for_rxg(self, ip: str) -> bool:
        """
        Checks that the expected WLAN Pi control node on an rXg is present and responsive on an IP address,
        which would indicate that it's a viable controller.
        """
        api_client = ApiClient(verify_ssl=False, timeout=5)

        try:
            resp = api_client.check_device(ip)

        except (ConnectTimeout, ConnectionError) as e:
            self.logger.warning(f"Testing of address {ip} failed: {e}")
            return False

        if resp.status_code == 200:
            try:
                data = resp.json()  # Try to parse the JSON
            except json.JSONDecodeError:
                return False
            else:
                if 'status' in data.keys():
                    return True
        return False


    # /etc/wlanpi-rxg-agent/

    def find_rxg(self, max_hops=3):
        # Check if an override server is configured, validate and use it if so.
        if self.override_server and self.test_address_for_rxg(self.override_server):
            return self.override_server

        first_gateway = utils.get_default_gateways().get('eth0', None)

        if not first_gateway:
            raise RXGAgentException("Unable to find first gateway on eth0")

        if self.test_address_for_rxg(first_gateway):
            return first_gateway

        raw_hop_data:list[dict] = utils.trace_route("google.com")['hops']
        filtered_hops:list[dict] = list(filter(lambda e: len(e['probes']), raw_hop_data))

        # pp(filtered_hops)
        hop_addresses = [x["probes"][0]['ip'] for x in sorted(filtered_hops, key=lambda hop: hop["hop"])]

        for i, address in enumerate(hop_addresses):
            if i < max_hops and self.test_address_for_rxg(address):
                return address


        # Todo: insert fallback here
        if self.fallback_server and self.test_address_for_rxg(self.fallback_server):
            return self.fallback_server

        raise RXGAgentException("Unable to find an rXg.")

    def handle_registration(self) -> bool:
        try:
            self.api_client.ip = self.active_server
            self.logger.info(f"Checking if we need to register with {self.api_client.ip}")
            resp = self.api_client.check_device()
            if resp.status_code == 200:
                response_data = resp.json()
                self.registered =  response_data['status'] != "unregistered"

            self.reinitialize_cert_tool(partner_id=self.api_client.ip)
            if not self.registered:
                self.logger.info(f"Not registered with {self.api_client.ip}. Registering...")
                self.certification_complete = False
                # Reinitialize the certificate tool with the active server
                self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
                #self.csr = self.cert_tool.get_csr_as_pem(node_name=utils.get_hostname())
                self.reinitialize_cert_tool(partner_id=self.api_client.ip)

                registration_resp = self.api_client.register(
                    model= utils.get_model_info()['Model'],
                    csr=self.csr
                )

                if registration_resp.status_code == 200:
                    logger.info(f"Successfully registered with {self.active_server}")
                    self.registered = True
                else:
                    # If registration failed here due to a non-200 status code, there's not much the client can do except wait and try again later
                    logger.error(f"Registration failed. Server said: {registration_resp.status_code}: {registration_resp.content}")
                    return False

            # By now, the client should be registered. If not, we're waiting for a successful attempt
            # Attempt to get our cert and CA
            if self.registered:
                self.logger.info(f"Registered with {self.api_client.ip}. Attempting to get cert info.")
                get_cert_resp = self.api_client.get_cert()
                if get_cert_resp.status_code == 200:
                    # Registration has succeeded, we need to get our certs.
                    response_data = get_cert_resp.json()

                    if not response_data['status'] == 'approved':
                        self.logger.warning(f"Server has not approved registration yet. Waiting for next cycle.")
                        return False
                    if not response_data['certificate']:
                        self.logger.warning(f"Server has not provided a certificate. Waiting for next cycle")
                        return False

                    self.cert_tool.save_cert_from_pem(response_data['certificate'])
                    self.cert_tool.save_ca_from_pem(response_data['ca'])
                    self.certification_complete = True
                    return True

            return False
        except (ConnectTimeout, ConnectionError) as e:
            self.logger.warning(f"Registration with {self.active_server} failed: {e}")
            return False


    def configure_mqtt_bridge(self):
        # Todo: Implement
        logger.debug("I'm configuring!")

        self.active_server = self.new_server
        if self.handle_registration():
            self.new_server = None

        return
        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        manager.EnableUnitFiles(['picockpit-client.service'], False, True)
        manager.Reload()
        job = manager.RestartUnit('picockpit-client.service', 'fail')


        pass

    
    def check_for_new_server(self):
        # if not self.active_server:
        #     return

        # if self.new_server and:
        #     self.logger.info("Server reconfig in process, skipping new server check")

        new_server = None
        try:
            new_server = self.find_rxg()
        except RXGAgentException as e:
            self.logger.warning("Check for new server failed--no valid possibilities were found")
        
        # Check if we found a new one and if it's different
        
        if new_server and new_server != self.active_server:
            self.logger.info(f"New or higher-precedence server found, dropping {self.active_server} and reconfiguring for {new_server} ")
            self.new_server = new_server
            self.configure_mqtt_bridge()

        if self.active_server == self.new_server and not self.certification_complete:
            self.logger.info(f"")
        

    def setup(self):
        self.check_for_new_server()
        # self.handle_registration()
        self.scheduled_jobs.append(schedule.every(20).seconds.do(self.check_for_new_server))

    def main_loop(self):
        schedule.run_pending()

def main():
    # Todo: load override
    # Todo: Test behavior on ssl failure

    agent = RXGAgent(verify_ssl=False)

    agent.setup()
    while True:
        agent.main_loop()
        time.sleep(1)

    # print(agent.find_rxg())
    pp(utils.get_model_info())
    # pp(find_rxg())
    return None