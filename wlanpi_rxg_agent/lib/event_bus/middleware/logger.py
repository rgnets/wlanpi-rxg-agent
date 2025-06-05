import logging
import typing as t

# Heavily inspired by the Tactician Logger Middleware :-)
# @link https://github.com/thephpleague/tactician-logger

# pylint: disable=too-few-public-methods


class LoggingMiddlewareConfig(t.NamedTuple):
    msg_received_level: int = logging.DEBUG
    msg_succeeded_level: int = logging.DEBUG
    msg_failed_level: int = logging.ERROR
    include_msg_payload: bool = False


def get_logger_middleware(
    logger: logging.Logger, config: t.Optional[LoggingMiddlewareConfig] = None
) -> t.Callable:
    # pylint: disable=E1120
    middleware_config: LoggingMiddlewareConfig = config or LoggingMiddlewareConfig()

    def logger_middleware(message: object, next_: t.Callable) -> object:
        message_type = type(message)

        log_msg = f"Message received: ${message_type}"
        if middleware_config.include_msg_payload:
            log_msg += f" with payload: {message}"

        logger.log(middleware_config.msg_received_level, log_msg)

        try:
            result = next_(message)
        except Exception as err:
            log_msg = f"Message failed: ${message_type}"
            if middleware_config.include_msg_payload:
                log_msg += f" with payload: {message}"
            logger.log(
                middleware_config.msg_failed_level,
                log_msg,
                exc_info=True,
            )
            raise err

        # log_msg = f"Message succeeded: ${message_type}"
        # if middleware_config.include_msg_payload:
        #     log_msg += f" with payload: {message}"

        logger.log(
            middleware_config.msg_succeeded_level, f"Message succeeded: ${message_type}"
        )

        return result

    return logger_middleware
