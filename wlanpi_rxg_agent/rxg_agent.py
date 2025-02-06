import asyncio
import json
import subprocess

from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
import os
from asyncio import Task
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Any

import wlanpi_rxg_agent.utils as utils
from busses import message_bus, command_bus
import lib.domain as agent_domain
import lib.rxg_supplicant.domain as supplicant_domain
from lib.rxg_supplicant.supplicant import RxgSupplicant
from rxg_mqtt_client import RxgMqttClient
from lib.configuration.bridge_config_file import BridgeConfigFile
from wlanpi_rxg_agent.bridge_control import BridgeControl
from wlanpi_rxg_agent.certificate_tool import CertificateTool

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(logging.INFO)

# CONFIG_DIR = "/etc/wlanpi-rxg-agent"
# CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
# BRIDGE_CONFIG_DIR = "/etc/wlanpi-mqtt-bridge"
# BRIDGE_CONFIG_FILE = os.path.join(BRIDGE_CONFIG_DIR, "config.toml")


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

        self.executor  = ThreadPoolExecutor(1)


    def setup_listeners(self):
        message_bus.add_handler(supplicant_domain.Messages.NewCertifiedConnection, self.certified_handler)
        message_bus.add_handler(agent_domain.Messages.ShutdownStarted, self.shutdown_handler)

    async def certified_handler(self, event: supplicant_domain.Messages.Certified) -> None:
        # Reconfigure MQTT Bridge
        self.logger.info("Reconfiguring Bridge")
        # Try to load existing toml and preserve. If we fail, it doesn't matter that much.
        async with self.bridge_config_lock:
            self.bridge_config_file.load_or_create_defaults()

            # Rewrite Bridge's config.toml
            self.bridge_config_file.data["MQTT"]["server"] = event.host
            self.bridge_config_file.data["MQTT"]["port"] = event.port
            self.bridge_config_file.data["MQTT_TLS"]["use_tls"] = True
            self.bridge_config_file.data["MQTT_TLS"]["ca_certs"] = event.ca_file
            self.bridge_config_file.data["MQTT_TLS"]["certfile"] = event.certificate_file
            self.bridge_config_file.data["MQTT_TLS"]["keyfile"] = event.key_file
            self.bridge_config_file.save()

            self.logger.info("Bridge config written. Restarting service.")
            self.bridge_control.restart()

    async def shutdown_handler(self, event: agent_domain.Messages.ShutdownStarted) -> None:
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


eth0_res = subprocess.run(
    "jc ifconfig eth0", capture_output=True, text=True, shell=True
)

eth0_data = json.loads(eth0_res.stdout)[0]
eth0_mac = eth0_data["mac_addr"]



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    # ml_models["answer_to_everything"] = fake_answer_to_everything_ml_model


    # agent = RXGAgent(
    #     verify_ssl=False,
    #     event_bus=event_bus,
    # )
    supplicant = RxgSupplicant()
    rxg_mqtt_client = RxgMqttClient(identifier=eth0_mac)
    message_bus.handle(agent_domain.Messages.StartupComplete())
    # asyncio.create_task(every(2, lambda : print("Ping")))
    # asyncio.create_task(every(3, lambda : print("Pong")))
    yield
    message_bus.handle(agent_domain.Messages.ShutdownStarted())
    await rxg_mqtt_client.stop_two()
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

