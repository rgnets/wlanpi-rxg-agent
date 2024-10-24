import json
import logging
import os
import time
from collections import defaultdict
from typing import Optional

import dbus
import schedule
import toml
from requests import ConnectionError, ConnectTimeout

import wlanpi_rxg_agent.utils as utils
from wlanpi_rxg_agent.api_client import ApiClient
from wlanpi_rxg_agent.certificate_tool import CertificateTool
from wlanpi_rxg_agent.models.exceptions import RXGAgentException

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.INFO)

CONFIG_DIR = "/etc/wlanpi-rxg-agent"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"
BRIDGE_CONFIG_FILE = os.path.join(BRIDGE_CONFIG_DIR, "config.toml")


class RXGAgent:

    def __init__(
        self,
        verify_ssl: bool = True,
        config_path: str = CONFIG_FILE,
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
        self.cert_dir = os.path.join(CONFIG_DIR, "certs")
        os.makedirs(self.cert_dir, exist_ok=True)
        os.chmod(self.cert_dir, 0o755)
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
        self.current_ca = ''
        self.current_cert = ''

    def reinitialize_cert_tool(self, partner_id: Optional[str] = None):
        self.cert_tool = CertificateTool(
            cert_directory=self.cert_dir, partner_id=partner_id
        )
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())

    def load_config(self) -> None:
        """
        Loads configuration from the defined config file
        """
        self.logger.info(f"Loading config file from {self.config_path}")
        if os.path.exists(self.config_path):
            config = toml.load(self.config_path)
        else:
            self.logger.error(f"Cannot find config file! Check {self.config_path}")
            raise RXGAgentException(
                f"Cannot find config file! Check {self.config_path}"
            )
        general_config = config["General"]
        self.override_server = general_config.get("override_rxg", None)
        self.fallback_server = general_config.get("fallback_rxg", None)

    def test_address_for_rxg(self, ip: str) -> bool:
        """
        Checks that the expected WLAN Pi control node on an rXg is present and
        responsive on an IP address, which would indicate that it's a viable
        controller.
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
                if "status" in data.keys():
                    return True
        return False

    # /etc/wlanpi-rxg-agent/

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


    def get_client_cert(self):
        get_cert_resp = self.api_client.get_cert()
        if get_cert_resp.status_code == 200:
            # Registration has succeeded, we need to get our certs.
            response_data = get_cert_resp.json()
            self.logger.debug(f"Get Cert Response: {json.dumps(response_data)}")

            return True, response_data["status"], response_data["ca"], response_data["certificate"], response_data["port"]
        else:
            self.logger.warning(f"get_client_cert failed: {get_cert_resp.status_code}: {get_cert_resp.reason} ")
            return False, None, None, None, None


    def renew_client_cert(self):
        get_cert_success, status, ca_str, cert_str, port = self.get_client_cert()
        if get_cert_success:
            if not status == "approved":
                self.logger.warning(
                    "Server has not approved registration yet. Waiting for next cycle."
                )
                return False
            if not cert_str:
                self.logger.warning(
                    "Server has not provided a certificate. Waiting for next cycle"
                )
                return False

            self.current_cert = cert_str
            self.cert_tool.save_cert(cert_str)
            self.current_ca = ca_str
            self.cert_tool.save_ca(ca_str)
            self.active_port = port
            return True
        return False

    def handle_registration(self) -> bool:
        try:
            self.api_client.ip = self.active_server
            self.logger.info(
                f"Checking if we need to register with {self.api_client.ip}"
            )
            resp = self.api_client.check_device()
            if resp.status_code == 200:
                response_data = resp.json()
                self.registered = response_data["status"] != "unregistered"

            self.reinitialize_cert_tool(partner_id=self.api_client.ip)
            if not self.registered:
                self.logger.info(
                    f"Not registered with {self.api_client.ip}. Registering..."
                )
                self.certification_complete = False
                # Reinitialize the certificate tool with the active server
                self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
                self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())

                registration_resp = self.api_client.register(
                    model=utils.get_model_info()["Model"], csr=self.csr
                )

                if registration_resp.status_code == 200:
                    self.logger.info(
                        f"Successfully registered with {self.active_server}"
                    )
                    self.registered = True
                else:
                    # If registration failed here due to a non-200 status code, there's not much
                    # the client can do except wait and try again later
                    self.logger.error(
                        f"Registration failed. Server said: {registration_resp.status_code}:"
                        f" {registration_resp.content}"
                    )
                    return False

            # By now, the client should be registered. If not, we're waiting for a successful attempt.
            # Attempt to get our cert and CA
            if self.registered:
                self.logger.info(
                    f"Registered with {self.api_client.ip}. Attempting to get cert info."
                )
                return self.renew_client_cert()

            return False
        except (ConnectTimeout, ConnectionError) as e:
            self.logger.warning(f"Registration with {self.active_server} failed: {e}")
            return False

    def configure_mqtt_bridge(self):
        logger.info("Reconfiguring Bridge")
        # Try to load existing toml and preserve. If we fail, it doesn't matter that much.
        data = defaultdict(dict)
        try:
            data = toml.load(BRIDGE_CONFIG_FILE)
            self.logger.info("Existing config loaded. Updating.")
        except toml.decoder.TomlDecodeError as e:
            self.logger.warning(
                f"Unable to decode existing bridge config, overwriting. Error: {e.msg}"
            )
        # Rewrite Bridge's config.toml
        data["MQTT"]["server"] = self.active_server
        data["MQTT"]["port"] = self.active_port
        data["MQTT_TLS"]["use_tls"] = True
        data["MQTT_TLS"]["ca_certs"] = self.cert_tool.ca_file
        data["MQTT_TLS"]["certfile"] = self.cert_tool.cert_file
        data["MQTT_TLS"]["keyfile"] = self.cert_tool.key_file
        data["MQTT_TLS"]["cert_reqs"] = 2

        self.logger.info("Bridge config written. Restarting service.")

        # [MQTT]
        # oldserver = rxg.ketchel.xyz
        # server = 192.168.20.81
        # port = 1883
        #
        # # The server to connect to
        # # <gateway> will cause the bridge to attempt to connect to the gateway device at the default route
        # #server = <gateway>
        # #port = 8884
        #
        # # Optional, only takes effect if use_tls is set
        # [MQTT_TLS]
        # use_tls = false
        # ca_certs =/home/wlanpi/dev/wlanpi-mqtt-bridge/certs/combined.ca.crt
        # certfile =/home/wlanpi/dev/wlanpi-mqtt-bridge/certs/client.crt
        # keyfile = /home/wlanpi/dev/wlanpi-mqtt-bridge/certs/client.key
        # # Verification of cert: 0=No verify, 1=Optional, 2=Required
        # cert_reqs = 0
        # # TLS version to use. Leave blank for any version.
        # #tls_version =
        # #ciphers =
        # #keyfile_password =

        with open(BRIDGE_CONFIG_FILE, "w") as f:
            toml.dump(data, f)

        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object(
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
        )
        manager = dbus.Interface(systemd1, "org.freedesktop.systemd1.Manager")
        try:
            manager.EnableUnitFiles(["wlanpi-mqtt-bridge.service"], False, True)
            manager.Reload()
        except Exception as e:
            self.logger.error(f"Failed to enable and reload: {e}")
        try:
            manager.RestartUnit("wlanpi-mqtt-bridge.service", "fail")
        except Exception as e:
            self.logger.error(f"Failed to restart unit: {e}")
        else:
            self.logger.info("Restarted bridge service")

    def check_for_new_server(self) -> bool:
        # if not self.active_server:
        #     return

        # if self.new_server and:
        #     self.logger.info("Server reconfig in process, skipping new server check")

        try:
            new_server = self.find_rxg()
        except RXGAgentException:
            self.logger.warning(
                "Check for new server failed--no valid possibilities were found"
            )
            return True

        # Check if we found a new one and if it's different
        do_reconfigure = False
        if new_server and new_server != self.active_server:
            self.logger.info(
                f"New or higher-precedence server found, dropping {self.active_server}"
                f" and reconfiguring for {new_server} "
            )
            self.new_server = new_server
            do_reconfigure=True


        if self.active_server == self.new_server and not self.certification_complete:
            self.logger.info(
                "Incomplete certification. Kicking off reconfiguration process."
            )
            do_reconfigure = True

        if do_reconfigure:
            if self.new_server:
                self.active_server = self.new_server
            if self.handle_registration():
                self.new_server = None
            else:
                self.logger.warning(
                    "Server registration check failed. Aborting reconfiguration."
                )
                return False

            self.logger.info("Registration complete. Reconfiguring bridge.")
            self.configure_mqtt_bridge()
        return do_reconfigure

    def check_for_new_certs(self):
        get_cert_success, status, ca_str, cert_str, port = self.get_client_cert()

        if get_cert_success:
            need_to_reload = False
            if ca_str and ca_str != self.current_ca:
                self.logger.info("CA has changed! We need to reload.")
                need_to_reload = True
                # self.current_ca = ca_str
                # self.cert_tool.save_ca(ca_str)
            if cert_str and cert_str != self.current_cert:
                self.logger.info("Cert has changed! We need to reload.")
                need_to_reload = True
                # self.current_cert = cert_str
                # self.cert_tool.save_cert(cert_str)
            if port and port != self.active_port:
                self.logger.info("Cert has changed! We need to reload.")
                need_to_reload = True
                # self.active_port = port

            if need_to_reload:
                self.renew_client_cert()
                self.configure_mqtt_bridge()


        else:
            self.logger.warning("Unabled to check for new certs.")

    def do_periodic_checks(self):
        if not self.check_for_new_server():
            self.check_for_new_certs()


    def setup(self):
        self.check_for_new_server()
        # self.handle_registration()
        self.scheduled_jobs.append(
            schedule.every(20).seconds.do(self.do_periodic_checks)
        )

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
    # pp(utils.get_model_info())
    # pp(find_rxg())
    # return None
