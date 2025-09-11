import logging
import os

from wlanpi_rxg_agent.lib.event_bus import CommandBus, MessageBus
from wlanpi_rxg_agent.lib.event_bus.middleware.logger import (
    LoggingMiddlewareConfig,
    get_logger_middleware,
)

# logging_middleware_config = LoggingMiddlewareConfig(
#     msg_received_level=logging.INFO,
#     msg_succeeded_level=logging.INFO,
#     msg_failed_level=logging.CRITICAL,
#     include_msg_payload = True
# )
#
#
# command_logger = logging.getLogger("command_bus")
# command_fh = logging.FileHandler('command_bus.log')
# command_fh.setLevel(logging.DEBUG)
# command_logger.addHandler(command_fh)
# command_logging_middleware = get_logger_middleware(command_logger, logging_middleware_config)

def _env_on(name: str, default: str = "on") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_level(name: str, default: str = "INFO") -> int:
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARN,
        "warning": logging.WARN,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    return levels.get(os.environ.get(name, default).strip().lower(), logging.INFO)


BUS_LOG_ENABLED = _env_on("RXG_BUS_LOG", "on")
BUS_LOG_LEVEL = _env_level("RXG_BUS_LOG_LEVEL", "INFO")
BUS_LOG_PAYLOAD = _env_on("RXG_BUS_LOG_PAYLOAD", "off")

# Build middlewares based on env configuration
bus_middlewares = []
if BUS_LOG_ENABLED:
    bus_logger = logging.getLogger("wlanpi_rxg_agent.event_bus")
    logging_config = LoggingMiddlewareConfig(
        msg_received_level=BUS_LOG_LEVEL,
        msg_succeeded_level=BUS_LOG_LEVEL,
        msg_failed_level=logging.ERROR,
        include_msg_payload=BUS_LOG_PAYLOAD,
    )
    bus_middlewares.append(get_logger_middleware(bus_logger, logging_config))

command_bus = CommandBus(locking=False, middlewares=bus_middlewares)


#
# message_logger = logging.getLogger("message_bus")
# message_fh = logging.FileHandler('message_bus.log')
# message_fh.setLevel(logging.DEBUG)
# message_logger.addHandler(message_fh)
# message_logging_middleware = get_logger_middleware(message_logger, logging_middleware_config)

message_bus = MessageBus(middlewares=bus_middlewares)
# command_bus.add_handler(CreateCustomerCommand, handle_customer_creation)
