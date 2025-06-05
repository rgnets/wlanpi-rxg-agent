import typing as t
from dataclasses import dataclass
from enum import Enum


class RxgAgentEvents(Enum):
    STARTUP_COMPLETE = "STARTUP_COMPLETE"  # All core modules relying on the bus should be up and listening when this is dispatched.
    SHUTDOWN_STARTED = "SHUTDOWN_STARTED"  # Signals modules to start teardown
    SHUTDOWN_COMPLETE = "SHUTDOWN_COMPLETE"


class Messages:
    class StartupComplete(t.NamedTuple):
        pass

    class ShutdownStarted(t.NamedTuple):
        pass

    class ShutdownComplete(t.NamedTuple):
        pass

    class AgentConfigUpdated(t.NamedTuple):
        pass

    @dataclass
    class AgentConfigUpdate:
        override_rxg: t.Optional[str] = None
        fallback_rxg: t.Optional[str] = None
        safe: bool = (
            False  # If the update should only succeed if the overrides match live servers
        )

    @dataclass
    class Error:
        msg: str
        exc: t.Optional[Exception]

    class MqttError(Error):
        pass
