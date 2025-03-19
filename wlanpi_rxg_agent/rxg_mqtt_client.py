import inspect
import re
from asyncio import AbstractEventLoop
from os import unlink
from ssl import SSLCertVerificationError
import ssl
from typing import Optional, Callable, Union, Any, Coroutine

import json
import logging

import random
import string

import socket
import time
import paho.mqtt.client as mqtt
# import schedule
import asyncio
import aiomqtt
from aiomqtt import TLSParameters, MqttError
from aiomqtt.types import PayloadType
from paho.mqtt.properties import Properties

from busses import message_bus, command_bus
import lib.domain as agent_domain
import lib.rxg_supplicant.domain as supplicant_domain
import lib.agent_actions.domain as actions_domain
from api_client import ApiClient
from kismet_control import KismetControl
from lib.configuration.agent_config_file import AgentConfigFile
from lib.configuration.bootloader_config_file import BootloaderConfigFile
from lib.configuration.bridge_config_file import BridgeConfigFile
from lib.wifi_control.wifi_control_wpa_supplicant import WiFiControlWpaSupplicant
from structures import TLSConfig, MQTTResponse
import utils

from utils import run_command_async


class RxgMqttClient:
    __global_base_topic = "wlan-pi/all/agent"

    def __init__(
            self,
            identifier: Optional[str] = None
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self.use_tls = True
        self.run = False
        self.connected = False

        self.mqtt_server = None
        self.mqtt_port = None
        # self.wifi_control = WiFiControlWpaSupplicant()

        self.my_base_topic = f"wlan-pi/{identifier}/agent"

        # Dummy declaration for type safety. Real client is created on startup hook
        self.mqtt_client = aiomqtt.Client('127.0.0.1')

        # Endpoints in the core that should be routinely polled and updated
        # This may go away if we can figure out to do event-based updates
        # ['Topic', retain]
        self.monitored_core_endpoints: list[tuple[str, bool]] = [
            #     ("api/v1/network/ethernet/all/vlan/all", True),
            #     ("api/v1/network/ethernet/all", True),
            #     ("api/v1/network/interfaces", True),
        ]

        # Topics that the bridge itself populates and publishes:
        # [topic, function to call, retain
        self.autopublished_topics: list[tuple[str, Callable, bool]] = [
            # ("status", lambda: "Connected", True),
            # (
            #     "addresses",
            #     lambda: MQTTResponse(data=utils.get_interface_ip_addr()),
            #     True,
            # ),
        ]

        # Topics to monitor for changes
        self.topics_of_interest: list[str] = [
            f"{self.__global_base_topic}/#",
            f"{self.my_base_topic}/#"
        ]

        # Holds scheduled jobs from `scheduler` so we can clean them up
        # on exit.
        # self.scheduled_jobs: list[schedule.Job] = []

        self.agent_config = AgentConfigFile()
        self.bridge_config = BridgeConfigFile()


        self.message_handler_pairs = [
            (supplicant_domain.Messages.NewCertifiedConnection, self.certified_handler),
            (supplicant_domain.Messages.RestartInternalMqtt, self.certified_handler),
            (agent_domain.Messages.ShutdownStarted, self.shutdown_handler),
            # (agent_domain.Messages.StartupComplete, self.startup_complete_handler),
            # (agent_domain.Messages.AgentConfigUpdate, self.config_update_handler),
        ]

        self.setup_listeners()
        self.mqtt_listener_task: Any = None


    def setup_listeners(self):
        for message, handler in self.message_handler_pairs:
            message_bus.add_handler(message, handler)

    def teardown_listeners(self):
        for message, handler in self.message_handler_pairs:
            message_bus.remove_handler(message, handler)

    async def shutdown_handler(self, event: agent_domain.Messages.ShutdownStarted) -> None:
        if self.run:
            await self.stop()

    async def listen(self, client:aiomqtt.Client):
        async for message in self.mqtt_client.messages:
            # self.logger.info(f"Got message {message}: {message.payload}")
            await self.handle_message(self.mqtt_client, message)

    async def certified_handler(self, event:supplicant_domain.Messages.Certified) -> None:
        if self.run:
            try:
                await self.stop()
            except aiomqtt.exceptions.MqttCodeError as e:
                self.logger.warning(f"Failed to stop Agent MQTT: {e}", exc_info=True)
        self.run = True
        tls_config = TLSConfig(ca_certs=event.ca_file, certfile=event.certificate_file, keyfile=event.key_file,
                               cert_reqs=ssl.VerifyMode(event.cert_reqs), tls_version=ssl.PROTOCOL_TLSv1_2,
                               ciphers=None) if self.use_tls else None
        self.mqtt_server = event.host
        self.mqtt_port = event.port

        try:
            async with aiomqtt.Client(
                event.host,
                port=event.port,
                tls_params=TLSParameters(**tls_config.__dict__) if tls_config else None,
                will=aiomqtt.Will(f"{self.my_base_topic}/status", "Abnormally Disconnected", 1, True)
            ) as c:
                # Make client globally available
                self.mqtt_client = c
                self.logger.info(
                    f"Connected to MQTT server at {self.mqtt_server}:{self.mqtt_port}."
                )

                self.logger.info("Subscribing to topics of interest.")
                # Subscribe to the topics we're going to care about.
                for topic in self.topics_of_interest:
                    self.logger.info(f"Subscribing to {topic}")
                    await self.mqtt_client.subscribe(topic)

                # Once we're ready, announce that we're connected:
                await self.mqtt_client.publish(f"{self.my_base_topic}/status", "Connected", 1, True)

                self.connected = True

                loop = asyncio.get_event_loop()
                self.mqtt_listener_task = loop.create_task(self.listen(self.mqtt_client))
                await self.mqtt_listener_task

        except (aiomqtt.exceptions.MqttError, aiomqtt.exceptions.MqttCodeError) as e:
            err_msg = "There was an error in the MQTT Listener"
            self.logger.error(err_msg, exc_info=True)
            message_bus.handle(agent_domain.Messages.MqttError(err_msg, e))
            message_bus.handle(supplicant_domain.Messages.RestartInternalMqtt(**event.__dict__))


    async def ping_batch_handler(self, event:Union[actions_domain.Messages.PingBatchComplete, actions_domain.Messages.PingBatchFailure]):

        await self.publish_with_retry(topic=f"{self.my_base_topic}/ingest/ping_batch", payload=event.to_json() )

    async def stop(self):
        self.logger.info("Stopping MQTTBridge")
        self.run = False
        await self.mqtt_client.publish(
            f"{self.my_base_topic}/status", "Disconnected", 1, True
        )
        if self.mqtt_listener_task is None:
            return
        # Cancel the task
        self.mqtt_listener_task.cancel()
        # Wait for the task to be cancelled
        try:
            await self.mqtt_listener_task
        except (aiomqtt.exceptions.MqttError, aiomqtt.exceptions.MqttCodeError) as e:
            err_msg = "There was an error in the MQTT Listener, but we were stopping it, so we don't care."
            self.logger.warn(err_msg, exc_info=True)
        except asyncio.CancelledError:
            pass

    async def add_subscription(self, topic) -> bool:
        """
        Adds an MQTT subscription, and tracks it for re-subscription on reconnect
        :param topic: The MQTT topic to subscribe to
        :return: Whether the subscription was successfully added
        """
        if topic not in self.topics_of_interest:
            result, mid = await self.mqtt_client.subscribe(topic)
            self.topics_of_interest.append(topic)
            self.logger.debug(f"Sub result: {str(result)}")
            return result == mqtt.MQTT_ERR_SUCCESS
        else:
            return True

    async def handle_message(self, client, msg) -> None:
        """
        Handles all incoming MQTT messages, usually dispatching them onward
        to the REST API
        :param client:
        :param msg:
        :return:
        """
        try:
            if (msg.topic.matches(self.my_base_topic + "/error")
                    or msg.topic.value.endswith('/_response')
                    or msg.topic.value.endswith('/status') or not (
                            msg.topic.matches(self.__global_base_topic + '/#') or msg.topic.matches(
                        self.my_base_topic + '/#'))):
                return

            self.logger.debug(
                f"Received message on topic '{msg.topic}': {str(msg.payload)}"
            )
            # response_topic = f"{msg.topic}/_response"
            is_global_topic = msg.topic.matches(self.__global_base_topic + '/#')
            bridge_ident = None
            if is_global_topic:
                subtopic = msg.topic.value.removeprefix(self.__global_base_topic + '/')
            else:
                subtopic = msg.topic.value.removeprefix(self.my_base_topic + '/')
            response_topic = f"{self.my_base_topic}/{subtopic}/_response"
            try:
                if msg.payload is not None and msg.payload not in ["", b""]:
                    try:
                        payload = json.loads(msg.payload)
                        bridge_ident = payload.get("_bridge_ident", None)
                        if bridge_ident is not None:
                            del payload["_bridge_ident"]
                        if not payload:
                            payload = None
                    except json.decoder.JSONDecodeError as e:
                        self.logger.error(f"Unable to decode payload as JSON: {str(e)}")
                        payload = msg.payload
                else:
                    payload = None
                self.logger.warning(f"Received message on topic '{msg.topic}': {str(msg.payload)}")
                self.logger.debug(f"Payload: {payload}")

                topic_handlers = {
                    "get_clients":
                        lambda: command_bus.handle(actions_domain.Commands.GetClients()),
                    "tcpdump_on_interface":
                        lambda: command_bus.handle(actions_domain.Commands.TCPDump(**payload, upload_ip=self.mqtt_server)),
                    "configure_radios":
                        lambda: command_bus.handle(actions_domain.Commands.ConfigureRadios(**payload)),
                    "override_rxg/set":
                        lambda : command_bus.handle(actions_domain.Commands.SetRxgs(override=payload["value"])),
                    "fallback_rxg/set":
                        lambda : command_bus.handle(actions_domain.Commands.SetRxgs(fallback=payload["value"])),
                    "password/set":
                        lambda : command_bus.handle(actions_domain.Commands.SetCredentials(user="wlanpi", password=payload['value'])),
                    "reboot":
                        lambda : command_bus.handle(actions_domain.Commands.Reboot()),
                    "configure/traceroutes":
                        lambda: command_bus.handle(actions_domain.Commands.ConfigureTraceroutes()),
                    "configure/ping_targets":
                        lambda: command_bus.handle(actions_domain.Commands.ConfigurePingTargets(targets=payload)),
                    "configure/agent":
                        lambda: command_bus.handle(actions_domain.Commands.ConfigureAgent(**payload)),
                }

                if subtopic in topic_handlers:
                    res = topic_handlers[subtopic]()

                    if isinstance(res, asyncio.Task):
                        res = await res
                    # The promise returned from the task will then be handled here
                    if inspect.iscoroutine(res):
                        res = await res

                    def custom_serializer(obj):
                        if callable(getattr(obj, "_json_encoder", None)):
                            return obj._json_encoder(obj)  # Convert to a dictionary
                        if callable(getattr(obj, "to_json", None)):
                            return obj.to_json()  # Convert to a dictionary
                        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

                    mqtt_response = MQTTResponse(status="success", data=json.dumps(res, default=custom_serializer))

                else:
                    mqtt_response = MQTTResponse(
                        status="validation_error",
                        errors=[
                            [
                                "RxgMqttClient.handle_message",
                                f"No handler for topic '{msg.topic}'",
                            ]
                        ]
                    )

                mqtt_response._bridge_ident = bridge_ident
                await self.default_callback(client=client,topic=response_topic,message=mqtt_response.to_json())

            except Exception as e:
                self.logger.error(f"Exception while handling message on topic '{msg.topic}'",exc_info=True)
                await self.mqtt_client.publish(
                    response_topic,
                    MQTTResponse(
                        status="agent_error",
                        errors=[[utils.get_full_class_name(e), str(e)]],
                        bridge_ident=bridge_ident,
                    ).to_json(),
                )

        except Exception as e:
            self.logger.error(f"Big nasty thing while handling message on topic '{msg.topic}'",exc_info=True)
            await self.mqtt_client.publish(
                self.my_base_topic + "/error",
                MQTTResponse(
                    status="agent_error",
                    errors=[[utils.get_full_class_name(e), str(e)]],
                ).to_json(),
            )

    async def publish_with_retry(
            self,
            topic: str,
            payload: PayloadType = None,
            qos: int = 0,
            retain: bool = False,
            properties: Optional[Properties] = None,
            *args: Any,
            timeout: Optional[float] = None,
            **kwargs: Any,
    ) -> None:
        """Publishes a message to the MQTT broker with retry logic.

        Args:
            topic: The topic to publish to.
            payload: The message payload.
            qos: The QoS level to use for publication.
            retain: If set to ``True``, the message will be retained by the broker.
            properties: (MQTT v5.0 only) Optional paho-mqtt properties.
            *args: Additional positional arguments to pass to paho-mqtt's publish
                method.
            timeout: The maximum time in seconds to wait for publication to complete.
                Use ``math.inf`` to wait indefinitely.
            **kwargs: Additional keyword arguments to pass to paho-mqtt's publish
                method.
        """
        attempts = 0
        MAX_ATTEMPTS = 3
        while attempts < MAX_ATTEMPTS:
            try:
                attempts += 1
                result = await self.mqtt_client.publish(topic, payload, qos, retain, properties, *args, timeout, **kwargs)  # Capture result
                return result  # Return the result if successful
            except MqttError:
                self.logger.exception(
                    f"Exception sending MQTT Message to {topic}. Attempt #{attempts} of {MAX_ATTEMPTS}")
                await asyncio.sleep(3)
        return None  # Return None if all attempts failed

    async def default_callback(self, client, topic, message: Union[str, bytes]) -> None:
        """
        Default callback for sending a REST response on to the MQTT endpoint.
        :param client:
        :param topic:
        :param message:
        :return:
        """
        info_msg_max_size = 100 #max chars for info logging
        stringified_message = str(message)
        if len(stringified_message) > info_msg_max_size:
            self.logger.info(f"Default callback. Topic: {topic} Message: {stringified_message[:info_msg_max_size]}... <truncated>")
        else:
            self.logger.info(f"Default callback. Topic: {topic} Message: {stringified_message[:info_msg_max_size]}... <truncated>")
        self.logger.debug(f"Default callback. Topic: {topic} Message: {stringified_message}")

        attempts=0
        MAX_ATTEMPTS = 3
        while attempts<MAX_ATTEMPTS:
            try:
                attempts+=1
                await client.publish(topic, message)
                break
            except MqttError:
                self.logger.exception(f"Exception in default MQTT callback. Attempt #{attempts} of {MAX_ATTEMPTS}")
                await asyncio.sleep(3)

    async def __aenter__(self) -> object:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.run:
            try:
                await self.stop()
            except aiomqtt.exceptions.MqttCodeError as e:
                self.logger.warning(f"Failed to stop Agent MQTT: {e}", exc_info=True)

    def __del__(self):
        self.teardown_listeners()
        if self.run:
            try:
                self.stop()
            except aiomqtt.exceptions.MqttCodeError as e:
                self.logger.warning(f"Failed to stop Agent MQTT: {e}", exc_info=True)


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.INFO)



    print("Done")
