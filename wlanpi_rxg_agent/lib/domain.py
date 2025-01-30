from enum import Enum
class RxgAgentEvents(Enum):
    STARTUP_COMPLETE = "STARTUP_COMPLETE"   # All core modules relying on the bus should be up and listening when this is dispatched.
    SHUTDOWN_STARTED = "SHUTDOWN_STARTED"   # Signals modules to start teardown
    SHUTDOWN_COMPLETE = "SHUTDOWN_COMPLETE"


import typing as t
class Messages:
    class StartupComplete(t.NamedTuple):
        pass
    class ShutdownStarted(t.NamedTuple):
        pass
    class ShutdownComplete(t.NamedTuple):
        pass