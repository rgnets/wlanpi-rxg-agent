import json
from json import JSONDecodeError

from lib.configuration.config_file import ConfigFile
from utils import run_command


class BootloaderConfigFile(ConfigFile):
    def __init__(self):
        self.data_part_path = "/dev/mmcblk0p1"
        super().__init__("/mnt/bldata.json")


    def load(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False)
            with open(self.config_file, "w") as f:
                self.data = json.load(f)
            run_command(f"umount {self.data_part_path}", shell=True, use_shlex=False)


    def save(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False)
            with open(self.config_file, "w") as f:
                json.dump(self.data, f)
            run_command(f"umount {self.data_part_path}", shell=True, use_shlex=False)

    def load_or_create_defaults(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            try:
                self.load()
            except FileNotFoundError as e:
                self.create_defaults()
                self.logger.warning(
                    f"Unable to open existing config, using defaults. Error: {e.msg}"
                )
            except JSONDecodeError as e:
                self.create_defaults()
                self.logger.warning(
                    f"Unable to decode existing config, using defaults. Error: {e.msg}"
                )

    def create_defaults(self):
        self.data = {
            "current_image_md5": "",
            "last_flash_success": True,
            "boot_exec_times": [],
            "first_boot": True,
            "remote_log": True,
            "boot_server_override": None,
            "boot_server_fallback": "piglet.rgnets.com",
            "device_type": "wlanpi",
        }

    @staticmethod
    def simulate_config() -> object:
        return {
            "current_image_md5": "2c84fecee801b51cedea18015e9abfea",
            "last_flash_success": True,
            "boot_exec_times": [],
            "first_boot": True,
            "remote_log": True,
            "boot_server_override": None,
            "boot_server_fallback": "piglet.rgnets.com",
            "device_type": "wlanpi",
        }

    @staticmethod
    def count_partitions() -> int:
        return int(run_command("ls -l /dev/mmcblk0p* | wc -l", shell=True, use_shlex=False).stdout.strip())


if __name__ == "__main__":
    boot = BootloaderConfigFile()
    boot.load()
    print(boot.data)