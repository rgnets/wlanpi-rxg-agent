import logging
try:
    import wlanpi_rxg_agent.utils as utils
    USE_COLOR = utils.supports_color()
except ImportError:
    # Fallback for when utils module has issues
    USE_COLOR = True


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
    fmt = "%(asctime)s | %(levelname)8s | %(name)s: %(message)s (%(filename)s:%(lineno)d)"

    USE_COLOR = USE_COLOR

    FORMATS = {
        logging.DEBUG: dark_grey + fmt + reset,
        logging.INFO: white + fmt + reset,
        logging.WARNING: orange + fmt + reset,
        logging.ERROR: red + fmt + reset,
        logging.CRITICAL: bold_red + fmt + reset
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


def setup_logging(level=logging.DEBUG, handlers=None):
    """Setup logging with custom formatter"""
    if handlers is None:
        handlers = [create_console_handler(level)]
    
    logging.basicConfig(
        encoding="utf-8",
        level=level,
        handlers=handlers,
        force=True
    )
    
    # Set common library log levels
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pyroute2.netlink.core").setLevel(logging.WARNING)
    logging.getLogger("pyroute2.ndb").setLevel(logging.WARNING)