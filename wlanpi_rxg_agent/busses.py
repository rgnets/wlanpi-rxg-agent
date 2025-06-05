import logging

from lib.event_bus import CommandBus, MessageBus
from lib.event_bus.middleware.logger import (
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

command_bus = CommandBus(
    locking=False,
    middlewares=[
        # command_logging_middleware
    ],
)


#
# message_logger = logging.getLogger("message_bus")
# message_fh = logging.FileHandler('message_bus.log')
# message_fh.setLevel(logging.DEBUG)
# message_logger.addHandler(message_fh)
# message_logging_middleware = get_logger_middleware(message_logger, logging_middleware_config)

message_bus = MessageBus(
    middlewares=[
        # message_logging_middleware
    ]
)
# command_bus.add_handler(CreateCustomerCommand, handle_customer_creation)
