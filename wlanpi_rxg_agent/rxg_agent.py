import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import wlanpi_rxg_agent.lib.domain as agent_domain
import wlanpi_rxg_agent.lib.rxg_supplicant.domain as supplicant_domain

# import wlanpi_rxg_agent.utils as utils
from wlanpi_rxg_agent.busses import message_bus
from fastapi import FastAPI, HTTPException
from wlanpi_rxg_agent.lib.agent_actions.actions import AgentActions
from wlanpi_rxg_agent.lib.configuration.bridge_config_file import BridgeConfigFile
from wlanpi_rxg_agent.lib.rxg_supplicant.supplicant import RxgSupplicant
from wlanpi_rxg_agent.lib.tasker.tasker import Tasker
from wlanpi_rxg_agent.lib.wifi_control.wifi_control_wpa_supplicant import WiFiControlWpaSupplicant
from wlanpi_rxg_agent.rxg_mqtt_client import RxgMqttClient
from wlanpi_rxg_agent.utils import aevery

from wlanpi_rxg_agent.bridge_control import BridgeControl
from wlanpi_rxg_agent.lib.network_control import NetworkControlManager

from wlanpi_rxg_agent.lib.logging_utils import setup_logging
from wlanpi_rxg_agent.models.api_models import DevShutdownRequest

# Setup logging with custom formatter
setup_logging(level=logging.DEBUG)

logger = logging.getLogger(__name__)

# Set specific log levels for various components
logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(logging.INFO)
logging.getLogger("rxg_agent").setLevel(logging.INFO)
logging.getLogger("api_client").setLevel(logging.INFO)
logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.event_bus._messagebus").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.event_bus._commandbus").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.rxg_supplicant.supplicant").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.wifi_control.wifi_control_wpa_supplicant").setLevel(logging.DEBUG)
logging.getLogger("rxg_mqtt_client").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.sip_control.mdk_baresip").setLevel(logging.INFO)
# logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.tasker.tasker").setLevel(logging.INFO)
logging.getLogger("wlanpi_rxg_agent.lib.network_control.network_control_manager").setLevel(logging.DEBUG)


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


    # Wifi control currently has no dependencies
    wifi_control = WiFiControlWpaSupplicant()
    tasker = Tasker()
    agent_actions = AgentActions()
    supplicant = RxgSupplicant()
    rxg_mqtt_client = RxgMqttClient(identifier=eth0_mac)
    
    # Get discovered wireless interfaces from WiFi control and initialize network control manager
    discovered_wireless_interfaces = set(wifi_control.get_discovered_wireless_interfaces())
    logger.info(f"Using discovered wireless interfaces for network control: {discovered_wireless_interfaces}")
    network_control = NetworkControlManager(wireless_interfaces=discovered_wireless_interfaces)
    await network_control.start()

    async def heartbeat_task():
        logger.debug("Heartbeat!")
        # await asyncio.sleep(10)

    message_bus.handle(agent_domain.Messages.StartupComplete())
    # asyncio.create_task(every(2, lambda : print("Ping")))
    heartbeat_task_handle = asyncio.create_task(aevery(3, heartbeat_task))

    try:
        yield
    except Exception as e:
        logger.error(f"Error during application lifecycle: {e}")
        raise
    finally:
        try:
            # Wrap entire shutdown in a timeout to prevent hanging
            async def shutdown_sequence():
                logger.info("Starting application shutdown...")
                message_bus.handle(agent_domain.Messages.ShutdownStarted())
                
                # Cancel background tasks first
                logger.info("Cancelling background tasks...")
                heartbeat_task_handle.cancel()
                try:
                    await heartbeat_task_handle
                except asyncio.CancelledError:
                    pass
                
                # Shutdown components with timeout and error handling
                shutdown_tasks = [
                    ("RXG MQTT Client", rxg_mqtt_client.stop),
                    ("Network Control Manager", network_control.stop),
                ]
                
                for component_name, shutdown_func in shutdown_tasks:
                    try:
                        logger.info(f"Shutting down {component_name}...")
                        await asyncio.wait_for(shutdown_func(), timeout=10.0)
                        logger.info(f"{component_name} shutdown completed")
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout waiting for {component_name} to shutdown")
                    except Exception as e:
                        logger.error(f"Error shutting down {component_name}: {e}")
                
                # Shutdown synchronous components
                try:
                    logger.info("Shutting down WiFi Control...")
                    wifi_control.shutdown()
                    logger.info("WiFi Control shutdown completed")
                except Exception as e:
                    logger.error(f"Error shutting down WiFi Control: {e}")
                    
                # Clean up other components if they have cleanup methods
                for component_name, component in [
                    ("Tasker", tasker),
                    ("Supplicant", supplicant),
                ]:
                    if hasattr(component, 'shutdown'):
                        try:
                            logger.info(f"Shutting down {component_name}...")
                            component.shutdown()
                            logger.info(f"{component_name} shutdown completed")
                        except Exception as e:
                            logger.error(f"Error shutting down {component_name}: {e}")
                    elif hasattr(component, 'cleanup'):
                        try:
                            logger.info(f"Cleaning up {component_name}...")
                            cleanup_result = component.cleanup()
                            if asyncio.iscoroutine(cleanup_result):
                                await asyncio.wait_for(cleanup_result, timeout=5.0)
                            logger.info(f"{component_name} cleanup completed")
                        except Exception as e:
                            logger.error(f"Error cleaning up {component_name}: {e}")
                
                logger.info("Application shutdown completed")
            
            # Give the entire shutdown process a maximum of 30 seconds
            await asyncio.wait_for(shutdown_sequence(), timeout=30.0)
            
        except asyncio.TimeoutError:
            logger.error("Shutdown sequence timed out after 30 seconds. Forcing exit.")
        except Exception as e:
            logger.error(f"Unexpected error during shutdown: {e}")
        finally:
            logger.info("Shutdown process finished")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/reload_agent")
async def reload_agent():
    message_bus.handle(agent_domain.Messages.AgentConfigUpdated())


@app.post("/dev_shutdown")
async def dev_shutdown(request: DevShutdownRequest):
    """Development endpoint to shutdown the application via SIGTERM."""
    if request.CONFIRM != 1:
        return {"message": "You must confirm the request by setting CONFIRM to 1"}
    
    logger.info("Dev shutdown requested - sending SIGTERM to own PID")
    os.kill(os.getpid(), signal.SIGTERM)
    
    return {"message": "Shutdown signal sent"}


#
# def startup():
#     import asyncio
#     @app.on_event("startup")
#     async def startup_event():
#         asyncio.create_task(main())
