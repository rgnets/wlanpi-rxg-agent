import logging
import os
import sys

def supports_color():
    """
    Returns True if the running system's terminal supports color, and False otherwise.
    """
    # Check for explicit override
    if os.environ.get('FORCE_COLOR', '').lower() in ('1', 'true', 'yes'):
        return True
    if os.environ.get('NO_COLOR', '').lower() in ('1', 'true', 'yes'):
        return False
    
    plat = sys.platform
    supported_platform = plat != 'Pocket PC' and (plat != 'win32' or 'ANSICON' in os.environ)

    # isatty is not always implemented, but also check for common development environments
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    
    # PyCharm and other IDEs often support color even when not a TTY
    ide_support = any(env in os.environ for env in ['PYCHARM_HOSTED', 'VSCODE_PID', 'TERM_PROGRAM'])
    
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