import logging
import os
import sys

from wlanpi_rxg_agent import constants
from wlanpi_rxg_agent.constants import IS_DEV


def supports_color():
    """
    Returns True if the running system's terminal supports color, and False otherwise.
    """
    # Check for explicit override
    if os.environ.get("FORCE_COLOR", "").lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("NO_COLOR", "").lower() in ("1", "true", "yes"):
        return False

    plat = sys.platform
    supported_platform = plat != "Pocket PC" and (
        plat != "win32" or "ANSICON" in os.environ
    )

    # isatty is not always implemented, but also check for common development environments
    is_a_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    # PyCharm and other IDEs often support color even when not a TTY
    ide_support = any(
        env in os.environ for env in ["PYCHARM_HOSTED", "VSCODE_PID", "TERM_PROGRAM"]
    )

    return supported_platform and (is_a_tty or ide_support)


USE_COLOR = supports_color()


# https://talyian.github.io/ansicolors/
class CustomFormatter(logging.Formatter):
    """Custom colored logging formatter with support for terminal colors"""

    red = "\x1b[31;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    blue = "\x1b[34;20m"
    magenta = "\x1b[35;20m"
    cyan = "\x1b[36;20m"
    white = "\x1b[38;5;255m"
    grey = "\x1b[38;20m"

    dark_grey = "\x1b[38;5;244m"
    orange = "\x1b[38;5;208m"

    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    fmt = (
        "%(asctime)s | %(levelname)8s | %(name)s: %(message)s (%(filename)s:%(lineno)d)"
    )

    USE_COLOR = USE_COLOR

    FORMATS = {
        logging.DEBUG: dark_grey + fmt + reset,
        logging.INFO: white + fmt + reset,
        logging.WARNING: orange + fmt + reset,
        logging.ERROR: red + fmt + reset,
        logging.CRITICAL: bold_red + fmt + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno) if self.USE_COLOR else self.fmt
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def create_console_handler(level=logging.DEBUG):
    """Create a console handler with the CustomFormatter"""
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(CustomFormatter())
    return handler


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


def setup_logging(level=logging.INFO, handlers=None):
    """Setup logging with custom formatter"""

    if IS_DEV:
        # Default to DEBUG for dev mode.
        level = logging.DEBUG

    # Allow env override for global app log level
    level = _env_level("RXG_LOG_LEVEL", str(level))

    if handlers is None:
        handlers = [create_console_handler(level)]

    logging.basicConfig(encoding="utf-8", level=level, handlers=handlers, force=True)

    # Set common library log levels
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pyroute2.netlink.core").setLevel(logging.WARNING)
    logging.getLogger("pyroute2.ndb").setLevel(logging.WARNING)


    if IS_DEV:
        # Set specific log levels for various components
        logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(logging.INFO)
        logging.getLogger("rxg_agent").setLevel(logging.INFO)
        logging.getLogger("api_client").setLevel(logging.INFO)
        logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
        logging.getLogger("wlanpi_rxg_agent.core_client").setLevel(logging.WARNING)
        logging.getLogger("wlanpi_rxg_agent.lib.event_bus._messagebus").setLevel(logging.INFO)
        logging.getLogger("wlanpi_rxg_agent.lib.event_bus._commandbus").setLevel(logging.INFO)
        logging.getLogger("wlanpi_rxg_agent.lib.rxg_supplicant.supplicant").setLevel(
            logging.INFO
        )
        logging.getLogger(
            "wlanpi_rxg_agent.lib.wifi_control.wifi_control_wpa_supplicant"
        ).setLevel(logging.DEBUG)
        logging.getLogger("wlanpi_rxg_agent.rxg_mqtt_client").setLevel(logging.INFO)
        logging.getLogger("wlanpi_rxg_agent.lib.sip_control").setLevel(
            logging.DEBUG if constants.BARESIP_DEBUG_OUTPUT else logging.INFO
        )
        # logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
        logging.getLogger("wlanpi_rxg_agent.lib.tasker.tasker").setLevel(logging.INFO)
        logging.getLogger(
            "wlanpi_rxg_agent.lib.network_control.network_control_manager"
        ).setLevel(logging.DEBUG)

    else:
        # Set specific log levels for various components
        logging.getLogger("wlanpi_rxg_agent.rxg_agent").setLevel(level)
        logging.getLogger("rxg_agent").setLevel(level)
        logging.getLogger("api_client").setLevel(level)
        logging.getLogger("apscheduler.scheduler").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.core_client").setLevel(logging.WARNING)
        # Bus logger levels can be overridden via RXG_BUS_LOG_LEVEL
        bus_level = _env_level("RXG_BUS_LOG_LEVEL", str(level))
        logging.getLogger("wlanpi_rxg_agent.lib.event_bus._messagebus").setLevel(bus_level)
        logging.getLogger("wlanpi_rxg_agent.lib.event_bus._commandbus").setLevel(bus_level)
        logging.getLogger("wlanpi_rxg_agent.lib.rxg_supplicant.supplicant").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.lib.wifi_control.wifi_control_wpa_supplicant").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.rxg_mqtt_client").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.lib.sip_control").setLevel(
            logging.DEBUG if constants.BARESIP_DEBUG_OUTPUT else level
        )
        # logging.getLogger("apscheduler.scheduler").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.lib.tasker.tasker").setLevel(level)
        logging.getLogger("wlanpi_rxg_agent.lib.network_control.network_control_manager").setLevel(level)
