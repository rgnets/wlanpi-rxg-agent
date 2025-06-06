import asyncio
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import lib.domain as agent_domain
import lib.rxg_supplicant.domain as supplicant_domain

# import wlanpi_rxg_agent.utils as utils
from busses import command_bus, message_bus
from fastapi import FastAPI
from lib.agent_actions.actions import AgentActions
from lib.configuration.bridge_config_file import BridgeConfigFile
from lib.rxg_supplicant.supplicant import RxgSupplicant
from lib.tasker.tasker import Tasker
from lib.wifi_control.wifi_control_wpa_supplicant import WiFiControlWpaSupplicant
from rxg_mqtt_client import RxgMqttClient
from utils import aevery

from wlanpi_rxg_agent.bridge_control import BridgeControl

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(logging.INFO)
logging.getLogger("lib.event_bus._messagebus").setLevel(logging.INFO)
logging.getLogger("lib.event_bus._commandbus").setLevel(logging.INFO)
logging.getLogger("lib.rxg_supplicant.supplicant").setLevel(logging.INFO)
logging.getLogger("rxg_mqtt_client").setLevel(logging.INFO)


class RXGAgent:

    def __init__(
        self,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.bridge_config_file = BridgeConfigFile()
        self.bridge_config_file.load_or_create_defaults()
        self.bridge_config_lock = asyncio.Lock()

        self.bridge_control = BridgeControl()

        self.executor = ThreadPoolExecutor(1)

        self.setup_listeners()

    def setup_listeners(self):
        self.logger.info("Setting up listeners")
        message_bus.add_handler(
            supplicant_domain.Messages.NewCertifiedConnection, self.certified_handler
        )
        message_bus.add_handler(
            agent_domain.Messages.ShutdownStarted, self.shutdown_handler
        )

    async def certified_handler(
        self, event: supplicant_domain.Messages.NewCertifiedConnection
    ) -> None:
        """Reconfigures the MQTT Bridge service whenever a new Certified event hits."""
        # Reconfigure MQTT Bridge
        self.logger.info("New certified connection. restarting MQTT Bridge")
        # Try to load existing toml and preserve. If we fail, it doesn't matter that much.
        async with self.bridge_config_lock:
            self.bridge_config_file.load_or_create_defaults()

            # Rewrite Bridge's config.toml
            self.bridge_config_file.data["MQTT"]["server"] = event.host
            self.bridge_config_file.data["MQTT"]["port"] = event.port
            self.bridge_config_file.data["MQTT_TLS"]["use_tls"] = True
            self.bridge_config_file.data["MQTT_TLS"]["ca_certs"] = event.ca_file
            self.bridge_config_file.data["MQTT_TLS"][
                "certfile"
            ] = event.certificate_file
            self.bridge_config_file.data["MQTT_TLS"]["keyfile"] = event.key_file
            self.bridge_config_file.save()

            self.logger.info("Bridge config written. Restarting service.")
            self.bridge_control.restart()

    async def shutdown_handler(
        self, event: agent_domain.Messages.ShutdownStarted
    ) -> None:
        self.logger.info("Shutting down Bridge")
        self.bridge_control.stop()

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


eth0_res = subprocess.run(
    "jc ifconfig eth0", capture_output=True, text=True, shell=True
)

eth0_data = json.loads(eth0_res.stdout)[0]
eth0_mac = eth0_data["mac_addr"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    # ml_models["answer_to_everything"] = fake_answer_to_everything_ml_model

    agent = RXGAgent(
        # verify_ssl=False,
        # event_bus=event_bus,
    )

    tasker = Tasker()

    # Wifi control currently has no dependencies
    wifi_control = WiFiControlWpaSupplicant()
    agent_actions = AgentActions()
    supplicant = RxgSupplicant()
    rxg_mqtt_client = RxgMqttClient(identifier=eth0_mac)

    async def heartbeat_task():
        logger.info("Heartbeat!")
        # await asyncio.sleep(10)

    message_bus.handle(agent_domain.Messages.StartupComplete())
    # asyncio.create_task(every(2, lambda : print("Ping")))
    asyncio.create_task(aevery(3, heartbeat_task))
    yield
    message_bus.handle(agent_domain.Messages.ShutdownStarted())
    await rxg_mqtt_client.stop()
    wifi_control.shutdown()
    # Clean up the ML models and release the resources
    # ml_models.clear()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/reload_agent")
async def reload_agent():
    message_bus.handle(agent_domain.Messages.AgentConfigUpdated())


#
# def startup():
#     import asyncio
#     @app.on_event("startup")
#     async def startup_event():
#         asyncio.create_task(main())
