import copy
import json
import logging
from collections import defaultdict
from os import PathLike
from typing import Union, Any

import toml


class ConfigFile():

    def __init__(self, config_file:Union[str, PathLike] = "config.toml", defaults: dict[str,Any] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__} for {config_file}")

        self.defaults = defaults
        if self.defaults is None:
            self.defaults = {}

        self.config_file = config_file
        self.data:dict[str,dict] = defaultdict(dict)

    def load(self):
        try:
            with open(self.config_file, "r") as config_file:
                if self.config_file.endswith(".toml"):
                    self.data = toml.load(config_file)
                else:
                    self.data = json.load(config_file)
                self.logger.debug("Existing config loaded.")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load config file: {e}")
            raise e
        except (toml.decoder.TomlDecodeError, json.decoder.JSONDecodeError) as e:
            self.logger.error(
                f"Unable to decode existing config. Error: {e.msg}"
            )
            raise e

    def save(self):
        with open(self.config_file, "w") as f:
            if self.config_file.endswith(".toml"):
                toml.dump(self.data, f)
            else:
                json.dump(self.data, f)


    def create_defaults(self):
        self.data = copy.deepcopy(self.defaults)

    def load_or_create_defaults(self, allow_empty: bool = False):
        try:
            self.load()
            if not self.data:
                self.logger.warning("Config file was empty, and allow_empty is false. Creating defaults")
                self.create_defaults()
        except FileNotFoundError as e:
            self.logger.warning(f"Unable to load config, using defaults. Error: {e}")
            self.create_defaults()
        except (toml.decoder.TomlDecodeError, json.decoder.JSONDecodeError) as e:
            self.create_defaults()
            self.logger.warning(
                f"Unable to decode existing config, using defaults. Error: {e.msg}"
            )
