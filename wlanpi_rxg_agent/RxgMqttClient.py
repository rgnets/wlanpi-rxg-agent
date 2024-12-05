import re
from ssl import SSLCertVerificationError
from typing import Optional, Callable, Union

import json
import logging
import socket
import time
import paho.mqtt.client as mqtt
import schedule

from kismet_control import KismetControl
from structures import TLSConfig, MQTTResponse
import utils


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
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.tls_config:
            self.mqtt_client.tls_set(**self.tls_config.__dict__)
        # self.core_client = CoreClient(base_url=self.core_base_url)

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
        self.autopublished_topics: list[tuple[str, Callable, bool]]= [
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


    def go(self):
        """
        Run the client. This calls the Paho client's `.loop_start()` method,
        which runs in the background until the Paho client is disconnected.
        :return:
        """
        self.logger.info("Starting RxgMqttClient")
        self.run = True

        def on_connect(client, userdata, flags, reason_code, properties) -> None:
            return self.handle_connect(client, userdata, flags, reason_code, properties)

        self.mqtt_client.on_connect = on_connect

        def on_message(client, userdata, msg) -> None:
            return self.handle_message(client, userdata, msg)

        self.mqtt_client.on_message = on_message
        self.mqtt_client.on_disconnect = lambda *args: self.handle_disconnect(*args)
        self.mqtt_client.on_connect_fail = lambda *args: self.handle_connect_fail(*args)

        self.mqtt_client.will_set(
            f"{self.my_base_topic}/status", "Abnormally Disconnected", 1, True
        )
        self.logger.info(
            f"Connecting to MQTT server at {self.mqtt_server}:{self.mqtt_port}"
        )

        while True:
            try:
                self.mqtt_client.connect(self.mqtt_server, self.mqtt_port, 60)
                break
            except ConnectionRefusedError:
                self.logger.error(
                    "Connection to MQTT server refused. Retrying in 10 seconds"
                )
                time.sleep(10)
            except socket.timeout:
                self.logger.error(
                    "Connection to MQTT server timed out. Retrying in 10 seconds"
                )
                time.sleep(10)
            except SSLCertVerificationError as e:
                self.logger.error(f"SSL Error. Retrying in 10 seconds. Error: {e}")
                time.sleep(10)

        # # Schedule some tasks with `https://schedule.readthedocs.io/en/stable/`
        # self.scheduled_jobs.append(
        #     schedule.every(10).seconds.do(self.publish_periodic_data)
        # )

        # Start the MQTT client loop,
        self.mqtt_client.loop_start()

        # while self.run:
        #     schedule.run_pending()
        #     time.sleep(1)

    def stop(self) -> None:
        """
        Closes the MQTT connection and shuts down any scheduled tasks for a clean exit.
        :return:
        """
        self.logger.info("Stopping MQTTBridge")
        self.run = False
        self.mqtt_client.publish(
            f"{self.my_base_topic}/status", "Disconnected", 1, True
        )
        self.mqtt_client.disconnect()
        self.mqtt_client.loop_stop()

        # for job in self.scheduled_jobs:
        #     schedule.cancel_job(job)
        #     self.scheduled_jobs.remove(job)

    def add_subscription(self, topic) -> bool:
        """
        Adds an MQTT subscription, and tracks it for re-subscription on reconnect
        :param topic: The MQTT topic to subscribe to
        :return: Whether the subscription was successfully added
        """
        if topic not in self.topics_of_interest:
            result, mid = self.mqtt_client.subscribe(topic)
            self.topics_of_interest.append(topic)
            self.logger.debug(f"Sub result: {str(result)}")
            return result == mqtt.MQTT_ERR_SUCCESS
        else:
            return True

    # noinspection PyUnusedLocal
    def handle_disconnect(self, client, *data) -> None:
        self.logger.warning(
            f"Disconnected from MQTT server at {self.mqtt_server}:{self.mqtt_port}!"
        )
        self.connected = False

        self.logger.warning(f"Disconnect details: {data}")

    # noinspection PyUnusedLocal
    def handle_connect_fail(self, client, *data) -> None:
        self.logger.warning(
            f"Failed to connect to MQTT server at {self.mqtt_server}:{self.mqtt_port}!"
        )
        self.connected = False
        self.logger.warning(f"Failure details: {data}")

    # noinspection PyUnusedLocal
    def handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        """
        Handles the connect event from Paho. This is called when a connection
        has been established, and we are ready to send messages.
        :param client: An instance of Paho's Client class that is used to send
         and receive messages
        :param userdata:
        :param flags:
        :param reason_code: The reason code that was received from the MQTT
         broker
        :param properties:
        :return:
        """

        self.logger.info(
            f"Connected to MQTT server at {self.mqtt_server}:{self.mqtt_port} with result code {reason_code}."
        )


        self.logger.info("Subscribing to topics of interest.")
        # Subscribe to the topics we're going to care about.
        for topic in self.topics_of_interest:
            self.logger.debug(f"Subscribing to {topic}")
            client.subscribe(topic)

        # Once we're ready, announce that we're connected:
        client.publish(f"{self.my_base_topic}/status", "Connected", 1, True)

        self.connected = True
        # Now do the first round of periodic data:
        # self.publish_periodic_data()


    def handle_message(self, client, userdata, msg) -> None:
        """
        Handles all incoming MQTT messages, usually dispatching them onward
        to the REST API
        :param client:
        :param userdata:
        :param msg:
        :return:
        """
        self.logger.debug(
            f"Received message on topic '{msg.topic}': {str(msg.payload)}"
        )
        self.logger.debug(f"User Data: {str(userdata)}")
        response_topic = f"{msg.topic}/_response"
        is_global_topic = msg.topic.startswith(self.__global_base_topic)
        bridge_ident = None
        if is_global_topic:
            subtopic = msg.topic.removeprefix(self.__global_base_topic)
        else:
            subtopic = msg.topic.removeprefix(self.my_base_topic)
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

            self.logger.warn(
                f"Received message on topic '{msg.topic}': {str(msg.payload)}"
            )
            self.logger.debug(
                f"Payload: {payload}"
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
            client.publish(
                response_topic,
                MQTTResponse(
                    status="bridge_error",
                    errors=[[utils.get_full_class_name(e), str(e)]],
                    bridge_ident=bridge_ident,
                ).to_json(),
            )


    def default_callback(self, client, topic, message: Union[str, bytes]) -> None:
        """
        Default callback for sending a REST response on to the MQTT endpoint.
        :param client:
        :param topic:
        :param message:
        :return:
        """
        self.logger.info(f"Default callback. Topic: {topic} Message: {str(message)}")
        client.publish(topic, message)

    def __enter__(self) -> object:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()
