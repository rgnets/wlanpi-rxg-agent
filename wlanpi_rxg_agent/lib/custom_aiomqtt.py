import asyncio
import logging
import ssl
from typing import Optional, Union, cast, Literal, Iterable, AsyncIterator, TypeVar

import aiomqtt
from aiomqtt import MqttReentrantError, MqttError
from aiomqtt.client import _set_client_socket_defaults, ProtocolVersion, Will, TLSParameters, ProxySettings, MQTT_LOGGER
from aiomqtt.message import Message
import paho.mqtt.client as mqtt
from aiomqtt.types import SocketOption, WebSocketHeaders
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

ClientT = TypeVar("ClientT", bound="Client")

class MessagesIterator:
    """Dynamic view of the client's message queue."""

    def __init__(self, client: ClientT) -> None:
        self._client = client

    def __aiter__(self) -> AsyncIterator[Message]:
        return self

    async def __anext__(self) -> Message:
        # Wait until we either (1) receive a message or (2) disconnect
        task = self._client._loop.create_task(self._client._queue.get())  # noqa: SLF001
        try:
            done, _ = await asyncio.wait(
                (task, self._client._disconnected),  # noqa: SLF001
                return_when=asyncio.FIRST_COMPLETED,
            )
        # If the asyncio.wait is cancelled, we must also cancel the queue task
        except asyncio.CancelledError:
            task.cancel()
            raise
        # When we receive a message, return it
        if task in done:
            return task.result()
        # If we disconnect from the broker, stop the generator with an exception
        task.cancel()
        msg = "Disconnected during message iteration"
        raise MqttError(msg)

    def __len__(self) -> int:
        """Return the number of messages in the message queue."""
        return self._client._queue.qsize()  # noqa: SLF001


class Client(aiomqtt.Client):

    def __init__(
        self,
        *,
        logger: Optional[logging.Logger] = None,
        identifier: Optional[str] = None,
        queue_type: Optional[type[asyncio.Queue[Message]]] = None,
        protocol: Optional[ProtocolVersion] = None,
        clean_session: Optional[bool] = None,
        transport: Literal["tcp", "websockets", "unix"] = "tcp",
        timeout: Optional[float] = None,
        max_queued_incoming_messages: Optional[int] = None,
        max_queued_outgoing_messages: Optional[int] = None,
        max_inflight_messages: Optional[int] = None,
        max_concurrent_outgoing_calls: Optional[int] = None,
        reconnect_on_failure: bool = False,
    ) -> None:
        # super(Client, self).__init__()

        self._loop = asyncio.get_running_loop()

        # Connection state
        self._connected: asyncio.Future[None] = asyncio.Future()
        self._disconnected: asyncio.Future[None] = asyncio.Future()
        self._lock: asyncio.Lock = asyncio.Lock()

        # Pending subscribe, unsubscribe, and publish calls
        self._pending_subscribes: dict[
            int,
            asyncio.Future[Union[tuple[int, ...], list[ReasonCode]]],
        ] = {}
        self._pending_unsubscribes: dict[int, asyncio.Event] = {}
        self._pending_publishes: dict[int, asyncio.Event] = {}
        self.pending_calls_threshold: int = 10
        self._misc_task: Optional[asyncio.Task[None]] = None

        # Queue that holds incoming messages
        if queue_type is None:
            queue_type = cast("type[asyncio.Queue[Message]]", asyncio.Queue)
        if max_queued_incoming_messages is None:
            max_queued_incoming_messages = 0
        self._queue = queue_type(maxsize=max_queued_incoming_messages)

        # Semaphore to limit the number of concurrent outgoing calls
        self._outgoing_calls_sem: Optional[asyncio.Semaphore]
        if max_concurrent_outgoing_calls is not None:
            self._outgoing_calls_sem = asyncio.Semaphore(max_concurrent_outgoing_calls)
        else:
            self._outgoing_calls_sem = None

        if protocol is None:
            protocol = ProtocolVersion.V311

        # Create the underlying paho-mqtt client instance
        self._client: mqtt.Client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=identifier,
            protocol=protocol.value,
            clean_session=clean_session,
            transport=transport,
            reconnect_on_failure=reconnect_on_failure,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_unsubscribe = self._on_unsubscribe
        self._client.on_message = self._on_message
        self._client.on_publish = self._on_publish

        # Callbacks for custom event loop
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write

        if max_inflight_messages is not None:
            self._client.max_inflight_messages_set(max_inflight_messages)
        if max_queued_outgoing_messages is not None:
            self._client.max_queued_messages_set(max_queued_outgoing_messages)

        if logger is None:
            logger = MQTT_LOGGER
        self._logger = logger
        self._client.enable_logger(logger)

        if timeout is None:
            timeout = 10
        self.timeout = timeout


    async def connect(
            self,
            hostname: str,
            port: int = 1883,
            keepalive: int = 60,
            bind_address: str = "",
            bind_port: int = 0,
            clean_start: mqtt.CleanStartOption = mqtt.MQTT_CLEAN_START_FIRST_ONLY,
            properties: Optional[Properties] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
            will: Optional[Will] = None,
            tls_context: Optional[ssl.SSLContext] = None,
            tls_params: Optional[TLSParameters] = None,
            tls_insecure: Optional[bool] = None,
            proxy: Optional[ProxySettings] = None,
            socket_options: Optional[Iterable[SocketOption]] = None,
            websocket_path: Optional[str] = None,
            websocket_headers: Optional[WebSocketHeaders] = None,
                      ):

        """Connect to the broker."""
        if self._lock.locked():
            msg = "The client context manager is reusable, but not reentrant"
            raise MqttReentrantError(msg)
        await self._lock.acquire()

        if username is not None:
            self._client.username_pw_set(username=username, password=password)

        # A little dirty, but allows us to switch SSL Contexts.
        self._client._ssl_context = None

        if tls_context is not None:
            self._client.tls_set_context(tls_context)

        if tls_params is not None:
            self._client.tls_set(
                ca_certs=tls_params.ca_certs,
                certfile=tls_params.certfile,
                keyfile=tls_params.keyfile,
                cert_reqs=tls_params.cert_reqs,
                tls_version=tls_params.tls_version,
                ciphers=tls_params.ciphers,
                keyfile_password=tls_params.keyfile_password,
            )

        if tls_insecure is not None:
            self._client.tls_insecure_set(tls_insecure)

        if proxy is not None:
            self._client.proxy_set(**proxy.proxy_args)

        if websocket_path is not None:
            self._client.ws_set_options(path=websocket_path, headers=websocket_headers)

        if will is not None:
            self._client.will_set(
                will.topic,
                will.payload,
                will.qos,
                will.retain,
                will.properties,
            )

        if socket_options is None:
            socket_options = ()
        _socket_options = tuple(socket_options)



        try:
            loop = asyncio.get_running_loop()
            # [3] Run connect() within an executor thread, since it blocks on socket
            # connection for up to `keepalive` seconds: https://git.io/Jt5Yc
            await loop.run_in_executor(
                None,
                self._client.connect,
                hostname,
                port,
                keepalive,
                bind_address,
                bind_port,
                clean_start,
                properties,
            )
            _set_client_socket_defaults(self._client.socket(), _socket_options)
        # Convert all possible paho-mqtt Client.connect exceptions to our MqttError
        # See: https://github.com/eclipse/paho.mqtt.python/blob/v1.5.0/src/paho/mqtt/client.py#L1770
        except (OSError, mqtt.WebsocketConnectionError) as exc:
            self._lock.release()
            raise MqttError(str(exc)) from None
        try:
            await self._wait_for(self._connected, timeout=None)
        except MqttError:
            # Reset state if connection attempt times out or CONNACK returns negative
            self._lock.release()
            self._connected = asyncio.Future()
            raise
        # Reset `_disconnected` if it's already in completed state after connecting
        if self._disconnected.done():
            self._disconnected = asyncio.Future()
        return self

    @property
    def messages(self) -> MessagesIterator:
        """Dynamic view of the client's message queue."""
        return MessagesIterator(self)

    async def disconnect(self, ack_timeout: Optional[int] = None):
        """Disconnect from the broker."""
        if self._disconnected.done():
            # Return early if the client is already disconnected
            if self._lock.locked():
                self._lock.release()
            if (exc := self._disconnected.exception()) is not None:
                # If the disconnect wasn't intentional, raise the error that caused it
                raise exc
            return

        # Try to gracefully disconnect from the broker
        rc = self._client.disconnect()
        if rc == mqtt.MQTT_ERR_SUCCESS:
            # Wait for acknowledgement
            await self._wait_for(self._disconnected, timeout=ack_timeout)
            # Reset `_connected` if it's still in completed state after disconnecting
            if self._connected.done():
                self._connected = asyncio.Future()
        else:
            self._logger.warning(
                "Could not gracefully disconnect: %d. Forcing disconnection.",
                rc,
            )
        # Force disconnection if we cannot gracefully disconnect
        if not self._disconnected.done():
            self._disconnected.set_result(None)
        # Release the reusability lock
        if self._lock.locked():
            self._lock.release()


