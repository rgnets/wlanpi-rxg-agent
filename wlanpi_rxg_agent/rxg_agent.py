import asyncio
import json
import logging
import os
import ssl
import subprocess
import time
from asyncio import Task
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Any

import toml
from requests import ConnectionError, ConnectTimeout, ReadTimeout

import wlanpi_rxg_agent.utils as utils
from lib.configuration.agent_config_file import AgentConfigFile
from lib.event_bus import EventBus
from lib.domain import RxgAgentEvents
from lib.rxg_supplicant.domain import RxgSupplicantEvents
from lib.rxg_supplicant.supplicant import RxgSupplicant
from rxg_mqtt_client import RxgMqttClient
from kismet_control import KismetControl
from lib.configuration.bridge_config_file import BridgeConfigFile
from structures import TLSConfig
from wlanpi_rxg_agent.api_client import ApiClient
from wlanpi_rxg_agent.bridge_control import BridgeControl
from wlanpi_rxg_agent.certificate_tool import CertificateTool
from wlanpi_rxg_agent.models.exceptions import RXGAgentException

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(logging.INFO)

CONFIG_DIR = "/etc/wlanpi-rxg-agent"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"
BRIDGE_CONFIG_FILE = os.path.join(BRIDGE_CONFIG_DIR, "config.toml")


class RXGAgent:

    def __init__(
        self,
        event_bus: EventBus,
        verify_ssl: bool = True,
        config_path: str = CONFIG_FILE,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing RXGAgent")

        self.bridge_config_file = BridgeConfigFile()
        self.bridge_config_file.load_or_create_defaults()
        self.bridge_config_lock = asyncio.Lock()
        self.agent_config_file = AgentConfigFile()
        self.agent_config_file.load_or_create_defaults()
        self.agent_config_lock = asyncio.Lock()

        self.event_bus = event_bus


        self.async_loop = asyncio.get_event_loop()

        self.verify_ssl = verify_ssl
        self.config_path = config_path

        self.override_server: Optional[str] = None
        self.fallback_server: Optional[str] = None
        self.active_server: Optional[str] = None
        self.new_server: Optional[str] = None

        self.active_port: Optional[int] = None
        self.new_port: Optional[int] = None

        self.load_config()

        self.registered = False
        self.certification_complete = False

        self.api_verify_ssl = False

        self.rxg_mqtt_client = RxgMqttClient(agent_reconfig_callback = self.handle_remote_agent_reconfiguration)
        self.bridge_control = BridgeControl()

        self.mqtt_task:Optional[Task] = None

        # Initialize certificates
        self.cert_dir = os.path.join(CONFIG_DIR, "certs")
        os.makedirs(self.cert_dir, exist_ok=True)
        os.chmod(self.cert_dir, 0o755)
        self.cert_tool = CertificateTool(cert_directory=self.cert_dir)
        self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())
        self.current_ca = ""
        self.current_cert = ""

        self.executor  = ThreadPoolExecutor(1)
        self.background_tasks: set[Task] = set()
    #
    # def reinitialize_cert_tool(self, partner_id: Optional[str] = None):
    #     self.cert_tool = CertificateTool(
    #         cert_directory=self.cert_dir, partner_id=partner_id
    #     )
    #     self.csr = self.cert_tool.get_csr(node_name=utils.get_hostname())

    def load_config(self) -> None:
        """
        Loads configuration from the defined config file
        """
        self.logger.info(f"Loading config file from {self.bridge_config_file.config_file}")
        # async with self.agent_config_lock:
        self.agent_config_file.load_or_create_defaults(allow_empty=False)
        self.override_server = self.agent_config_file.data.get('General').get("override_rxg", None)
        self.fallback_server = self.agent_config_file.data.get('General').get("fallback_rxg", None)


    #
    # # /etc/wlanpi-rxg-agent/
    #
    #
    # async def reconfigure_mqtt_client(self, server:str, port:int, use_tls:bool, ca_file:str, cert_file:str, key_file:str, cert_reqs:int):
    #     self.logger.info("Reconfiguring Internal MQTT Client")
    #     # Configure the internal client
    #
    #     # Shut down the existing client if it's running
    #     if self.rxg_mqtt_client is not None and (self.rxg_mqtt_client.connected or self.rxg_mqtt_client.run):
    #         self.logger.info("Stopping Internal MQTT Client")
    #         await self.rxg_mqtt_client.stop()
    #         del self.rxg_mqtt_client
    #
    #     eth0_res = subprocess.run(
    #         "jc ifconfig eth0", capture_output=True, text=True, shell=True
    #     )
    #
    #     eth0_data = json.loads(eth0_res.stdout)[0]
    #     eth0_mac = eth0_data["mac_addr"]
    #
    #     tls_config = TLSConfig(ca_certs=ca_file, certfile=cert_file, keyfile=key_file, cert_reqs=ssl.VerifyMode(cert_reqs), tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None) if use_tls else None
    #     self.logger.info(
    #         f"Reconfiguring MQTT client with server: {server}, port: {port}, tls: {use_tls}, ca_file: {ca_file}, cert_file: {cert_file}, key_file: {key_file}, cert_reqs: {cert_reqs}"
    #     )
    #     self.rxg_mqtt_client = RxgMqttClient(mqtt_server=server, mqtt_port=port, tls_config=tls_config, identifier=eth0_mac, agent_reconfig_callback = self.handle_remote_agent_reconfiguration)
    #     self.logger.info("Starting Internal MQTT Client")
    #
    #     self.mqtt_task = self.async_loop.create_task(self.rxg_mqtt_client.go())
    #     self.background_tasks.add(self.mqtt_task)
    #     self.mqtt_task.add_done_callback(self.background_tasks.remove)
    #
    # async def configure_mqtt_bridge(self):
    #     self.logger.info("Reconfiguring Bridge")
    #     # Try to load existing toml and preserve. If we fail, it doesn't matter that much.
    #     async with self.bridge_config_lock:
    #         self.bridge_config_file.load_or_create_defaults()
    #
    #         # Rewrite Bridge's config.toml
    #         self.bridge_config_file.data["MQTT"]["server"] = self.active_server
    #         self.bridge_config_file.data["MQTT"]["port"] = self.active_port
    #         self.bridge_config_file.data["MQTT_TLS"]["use_tls"] = True
    #         self.bridge_config_file.data["MQTT_TLS"]["ca_certs"] = self.cert_tool.ca_file
    #         self.bridge_config_file.data["MQTT_TLS"]["certfile"] = self.cert_tool.cert_file
    #         self.bridge_config_file.data["MQTT_TLS"]["keyfile"] = self.cert_tool.key_file
    #         self.bridge_config_file.save()
    #
    #         # Configure the internal client as well, as we transition to using it.
    #         await self.reconfigure_mqtt_client(self.active_server, self.active_port, True, self.cert_tool.ca_file, self.cert_tool.cert_file, self.cert_tool.key_file, 2)
    #
    #         self.logger.info("Bridge config written. Restarting service.")
    #         self.bridge_control.restart()
    #
    # async def check_for_new_server(self) -> bool:
    #     # if not self.active_server:
    #     #     return
    #
    #     # if self.new_server and:
    #     #     self.logger.info("Server reconfig in process, skipping new server check")
    #
    #     try:
    #         new_server = self.find_rxg()
    #     except RXGAgentException:
    #         self.logger.warning(
    #             "Check for new server failed--no valid possibilities were found"
    #         )
    #         return True
    #
    #     # Check if we found a new one and if it's different
    #     do_reconfigure = False
    #     if new_server and new_server != self.active_server:
    #         self.logger.info(
    #             f"New or higher-precedence server found, dropping {self.active_server}"
    #             f" and reconfiguring for {new_server} "
    #         )
    #         self.bridge_control.stop()
    #         self.new_server = new_server
    #         do_reconfigure = True
    #
    #     if self.active_server == self.new_server and not self.certification_complete:
    #         self.logger.info(
    #             "Incomplete certification. Kicking off reconfiguration process."
    #         )
    #         do_reconfigure = True
    #
    #     if do_reconfigure:
    #         if self.new_server:
    #             self.active_server = self.new_server
    #         if self.handle_registration():
    #             self.new_server = None
    #         else:
    #             self.logger.warning(
    #                 "Server registration check failed. Aborting reconfiguration."
    #             )
    #             return False
    #
    #         self.logger.info("Registration complete. Reconfiguring bridge.")
    #         await self.configure_mqtt_bridge()
    #     return do_reconfigure
    #
    # async def check_for_new_certs(self, server_ip: Optional[str] = None):
    #     if not server_ip:
    #         server_ip = self.active_server
    #     get_cert_success, status, ca_str, cert_str, host, port = self.get_client_cert(
    #         server_ip=server_ip
    #     )
    #
    #     if get_cert_success:
    #         need_to_reload = False
    #         if ca_str and ca_str != self.current_ca:
    #             self.logger.info("CA has changed! We need to reload.")
    #             need_to_reload = True
    #             # self.current_ca = ca_str
    #             # self.cert_tool.save_ca(ca_str)
    #         if cert_str and cert_str != self.current_cert:
    #             self.logger.info("Cert has changed! We need to reload.")
    #             need_to_reload = True
    #             # self.current_cert = cert_str
    #             # self.cert_tool.save_cert(cert_str)
    #         if port and port != self.active_port:
    #             self.logger.info("Cert has changed! We need to reload.")
    #             need_to_reload = True
    #             # self.active_port = port
    #         if host and host != self.active_server:
    #             self.logger.info("Server has changed! We need to reload.")
    #             need_to_reload = True
    #             # self.active_port = port
    #
    #         if need_to_reload:
    #             self.renew_client_cert()
    #             await self.configure_mqtt_bridge()
    #
    #     else:
    #         self.logger.warning("Unabled to check for new certs.")
    #
    # def check_registration_status(
    #     self, server_ip: Optional[str] = None
    # ) -> tuple[bool, str]:
    #     if not server_ip:
    #         server_ip = self.active_server
    #     api_client = ApiClient(server_ip=server_ip, verify_ssl=self.api_verify_ssl)
    #     self.logger.info(f"Checking registration status {api_client.ip}")
    #     resp = api_client.check_device()
    #     if resp.status_code == 200:
    #         response_data = resp.json()
    #         return (
    #             response_data["status"] in ["registered", "approved"],
    #             response_data["status"],
    #         )
    #     return False, "unknown"
    #
    # async def do_periodic_checks(self):
    #     try:
    #         self.logger.debug("Running periodic checks")
    #         registration_status = False
    #         if self.active_server:
    #             registration_status, reg_status_response = self.check_registration_status()
    #             self.registered = registration_status
    #             if not registration_status:
    #                 self.handle_registration()
    #             elif not reg_status_response.lower() == "approved":
    #                 self.logger.warning(
    #                     "Device has not been approved, decertifying and stopping bridge if it's running."
    #                 )
    #                 self.certification_complete = False
    #                 self.registered = False
    #                 self.bridge_control.stop()
    #             else:
    #                 if not self.certification_complete or not self.registered:
    #                     self.handle_registration()
    #
    #             # Check MQTT
    #             if self.registered and (not self.rxg_mqtt_client or self.rxg_mqtt_client.run == False or (self.mqtt_task is not None and self.mqtt_task.done())):
    #                 self.logger.warning("Mqtt task has died and should be running. Triggering reconfiguration of MQTT")
    #                 await self.reconfigure_mqtt_client(self.active_server, self.active_port, True,
    #                                                    self.cert_tool.ca_file, self.cert_tool.cert_file,
    #                                                    self.cert_tool.key_file, 2)
    #
    #         if not await self.check_for_new_server() and registration_status:
    #             await self.check_for_new_certs()
    #     except Exception as e:
    #         self.logger.error(f"Something went wrong during periodic checks: {e}", exc_info=e)
    #
    #
    # async def handle_remote_agent_reconfiguration(self, new_config:dict[str, Any]):
    #
    #     async with self.agent_config_lock:
    #         if "override_rxg" in new_config:
    #             self.override_server = new_config["override_rxg"]
    #         if "fallback_rxg" in new_config:
    #             self.fallback_server = new_config["fallback_rxg"]
    #
    #         self.agent_config_file.data["General"] = {
    #             "override_rxg": self.override_server,
    #             "fallback_rxg": self.fallback_server,
    #         }
    #         self.agent_config_file.save()
    #

    @staticmethod
    async def every(__seconds: float, func, *args, **kwargs):
        while True:
            func(*args, **kwargs)
            await asyncio.sleep(__seconds)


    @staticmethod
    async def aevery(__seconds: float, func, *args, **kwargs):
        while True:
            await func(*args, **kwargs)
            await asyncio.sleep(__seconds)

    async def go(self):
        # await self.check_for_new_server()
        periodic_task = self.async_loop.create_task(self.aevery(1, self.do_periodic_checks))
        self.background_tasks.add(periodic_task)
        periodic_task.add_done_callback(self.background_tasks.remove)
        # self.async_loop.run_forever()
        while True:
            if self.mqtt_task is not None and self.mqtt_task.done():
                self.logger.warning("Mqtt task may have died:", exc_info=self.mqtt_task.exception())



            await asyncio.sleep(0.5)



async def every(__seconds: float, func, *args, **kwargs):
    while True:
        func(*args, **kwargs)
        await asyncio.sleep(__seconds)



async def aevery(__seconds: float, func, *args, **kwargs):
    while True:
        await func(*args, **kwargs)
        await asyncio.sleep(__seconds)


async def async_wrapper(sync_task, *args):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sync_task, *args)

async def main():
    # Todo: load override
    # Todo: Test behavior on ssl failure

    event_bus = EventBus()

    agent = RXGAgent(
        verify_ssl=False,
        event_bus = event_bus,
    )
    supplicant = RxgSupplicant(event_bus=event_bus)

    # await asyncio.gather(event_bus.run(), agent.connect())
    await agent.go()




import asyncio
from contextlib import asynccontextmanager

import fastapi
from fastapi import FastAPI

event_bus = EventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    # ml_models["answer_to_everything"] = fake_answer_to_everything_ml_model


    # agent = RXGAgent(
    #     verify_ssl=False,
    #     event_bus=event_bus,
    # )
    supplicant = RxgSupplicant(event_bus=event_bus)

    event_bus.emit(RxgAgentEvents.STARTUP_COMPLETE, None)
    # asyncio.create_task(every(2, lambda : print("Ping")))
    # asyncio.create_task(every(3, lambda : print("Pong")))
    yield
    event_bus.emit("shutdown_started", None)
    # Clean up the ML models and release the resources
    # ml_models.clear()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/reload_agent")
async def reload_agent():
    event_bus.emit('agent_config_updated', None)

#
# def startup():
#     import asyncio
#     @app.on_event("startup")
#     async def startup_event():
#         asyncio.create_task(main())

