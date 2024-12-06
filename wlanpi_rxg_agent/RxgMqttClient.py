import re
from ssl import SSLCertVerificationError
from typing import Optional, Callable, Union

import json
import logging
import socket
import time
import paho.mqtt.client as mqtt
import schedule
import asyncio
import aiomqtt
from aiomqtt import TLSParameters

from kismet_control import KismetControl
from structures import TLSConfig, MQTTResponse
import utils
from utils import run_command_async


class RxgMqttClient:
    __global_base_topic = "wlan-pi/all/agent"

    def __init__(
            self,
            mqtt_server: str = "wi.fi",
            mqtt_port: int = 1883,
            tls_config: Optional[TLSConfig] = None,
            wlan_pi_core_base_url: str = "http://127.0.0.1:31415",
            kismet_base_url: str = "http://127.0.0.1:2501",
            identifier: Optional[str] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing RxgMqttClient")

        self.run = False
        self.connected = False

        self.mqtt_server = mqtt_server
        self.mqtt_port = mqtt_port
        self.tls_config = tls_config
        self.core_base_url = wlan_pi_core_base_url
        self.kismet_base_url = kismet_base_url

        self.my_base_topic = f"wlan-pi/{identifier}/agent"
        # self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client = aiomqtt.Client(
            mqtt_server,
            port=self.mqtt_port,
            tls_params=TLSParameters(**self.tls_config.__dict__) if self.tls_config else None,
            will=aiomqtt.Will(f"{self.my_base_topic}/status", "Abnormally Disconnected", 1, True)
        )

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
        self.scheduled_jobs: list[schedule.Job] = []

        self.kismet_control = KismetControl()

    async def go(self):
        """
        Run the client. This calls the Paho client's `.loop_start()` method,
        which runs in the background until the Paho client is disconnected.
        :return:
        """
        self.logger.info("Starting RxgMqttClient")
        self.run = True

        reconnect_interval = 5

        self.logger.info(
            f"Connecting to MQTT server at {self.mqtt_server}:{self.mqtt_port}"
        )
        while True:
            try:
                async with self.mqtt_client:
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
                    # Now do the first round of periodic data:
                    # self.publish_periodic_data()

                    async for message in self.mqtt_client.messages:
                        # self.logger.info(f"Got message {message}: {message.payload}")
                        await self.handle_message(self.mqtt_client, message)


            except aiomqtt.MqttError:

                self.connected = False
                if not self.run:
                    self.logger.warning("Run is false--not attempting to reconnect.")
                    break
                self.logger.warning(f"Connection lost; Reconnecting in {reconnect_interval} seconds ...")
                await asyncio.sleep(reconnect_interval)

        self.logger.info("Stopping MQTTBridge")

        # for job in self.scheduled_jobs:
        #     schedule.cancel_job(job)
        #     self.scheduled_jobs.remove(job)

    async def stop(self) -> None:
        """
        Closes the MQTT connection and shuts down any scheduled tasks for a clean exit.
        :return:
        """
        self.logger.info("Stopping MQTTBridge")
        self.run = False
        await self.mqtt_client.publish(
            f"{self.my_base_topic}/status", "Disconnected", 1, True
        )
        self.mqtt_client._client.disconnect()

        # for job in self.scheduled_jobs:
        #     schedule.cancel_job(job)
        #     self.scheduled_jobs.remove(job)

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
                        query_params = payload.get("_query_params", None)
                        if query_params is not None:
                            del payload["_query_params"]
                        if not payload:
                            payload = None
                    except json.decoder.JSONDecodeError as e:
                        self.logger.error(
                            f"Unable to decode payload as JSON: {str(e)}"
                        )
                        payload = msg.payload

                        # client.publish(
                        #     response_topic,
                        #     MQTTResponse(
                        #         status="rest_error",
                        #         rest_status=400,
                        #         rest_reason="Bad Request",
                        #     )
                        # )

                else:
                    query_params = None
                    payload = None

                self.logger.warning(
                    f"Received message on topic '{msg.topic}': {str(msg.payload)}"
                )
                self.logger.debug(
                    f"Payload: {payload}"
                )

                result = None

                if subtopic == "get_clients":
                    result = await self.exec_get_clients(self.mqtt_client)

                mqtt_response = MQTTResponse(
                    status="success",
                    rest_status="200",
                    rest_reason="OK",
                    data=json.dumps(result),
                    bridge_ident=bridge_ident,
                )

                await self.default_callback(
                    client=client,
                    topic=response_topic,
                    message=mqtt_response.to_json(),
                )

                # response = self.core_client.execute_request(
                #     method=route.method,
                #     path=route.route,
                #     data=payload if route.method.lower() != "get" else None,
                #     params=(
                #         payload
                #         if route.method.lower() == "get" and not query_params
                #         else query_params
                #     ),
                # )

                # mqtt_response = MQTTResponse(
                #     status="success" if response.ok else "rest_error",
                #     rest_status=response.status_code,
                #     rest_reason=response.reason,
                #     data=response.text,
                #     bridge_ident=bridge_ident,
                # )

                # mqtt_response = MQTTResponse(
                #     status="success" if True else "rest_error",
                #     rest_status=200,
                #     rest_reason="OK",
                #     data="Dummy Payload",
                #     bridge_ident=bridge_ident,
                # )
                # self.default_callback(
                #     client=client,
                #     topic=response_topic,
                #     message=mqtt_response.to_json(),
                # )
            except Exception as e:
                self.logger.error(
                    f"Exception while handling message on topic '{msg.topic}'",
                    exc_info=e,
                )
                await self.mqtt_client.publish(
                    response_topic,
                    MQTTResponse(
                        status="bridge_error",
                        errors=[[utils.get_full_class_name(e), str(e)]],
                        bridge_ident=bridge_ident,
                    ).to_json(),
                )

        except Exception as e:
            self.logger.error(
                f"Big nasty thing while handling message on topic '{msg.topic}'",
                exc_info=e,
            )
            await self.mqtt_client.publish(
                self.my_base_topic + "/error",
                MQTTResponse(
                    status="bridge_error",
                    errors=[[utils.get_full_class_name(e), str(e)]],
                ).to_json(),
            )

    async def exec_get_clients(self, client):
        if self.kismet_control.is_kismet_running():
            return self.kismet_control.get_seen_devices()
        else:
            return self.kismet_control.empty_seen_devices()



    # async def tcpdump_on_interface(self, interface_name):
    #     filename = '/tmp/output.pcap'
    #     cmd = ["tcpdump", "-i", interface_name, '-w', filename]
    #     await run_command_async(cmd)

    async def default_callback(self, client, topic, message: Union[str, bytes]) -> None:
        """
        Default callback for sending a REST response on to the MQTT endpoint.
        :param client:
        :param topic:
        :param message:
        :return:
        """
        self.logger.info(f"Default callback. Topic: {topic} Message: {str(message)}")
        await client.publish(topic, message)

    async def __aenter__(self) -> object:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(encoding="utf-8", level=logging.INFO)

    print("Done")
