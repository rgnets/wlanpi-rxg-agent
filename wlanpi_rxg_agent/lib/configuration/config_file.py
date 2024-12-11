import logging
from collections import defaultdict
from os import PathLike
from typing import Union

import toml


class ConfigFile():

    def __init__(self, config_file:Union[str, PathLike] = "config.toml"):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        self.config_file = config_file
        self.data:dict[str,dict] = defaultdict(dict)

    def load(self):
        try:
            self.data = toml.load(self.config_file)
            self.logger.debug("Existing config loaded.")
        except toml.decoder.TomlDecodeError as e:
            self.logger.warning(
                f"Unable to decode existing config. Error: {e.msg}"
            )
            raise e

    def save(self):
        with open(self.config_file, "w") as f:
            toml.dump(self.data, f)

    def create_defaults(self):
        self.data = defaultdict(dict)

    def load_or_create_defaults(self):
        try:
            self.load()
        except toml.decoder.TomlDecodeError as e:
            self.create_defaults()
            self.logger.warning(
                f"Unable to decode existing config, using defaults. Error: {e.msg}"
            )
