import copy
import json
from json import JSONDecodeError

from wlanpi_rxg_agent.lib.configuration.config_file import ConfigFile
from wlanpi_rxg_agent.utils import run_command


class BootloaderConfigFile(ConfigFile):
    def __init__(self):
        self.data_part_path = "/dev/mmcblk0p1"
        super().__init__(
            "/mnt/bldata.json",
            defaults={
                "current_image_md5": "",
                "last_flash_success": True,
                "boot_exec_times": [],
                "first_boot": True,
                "remote_log": True,
                "boot_server_override": None,
                "boot_server_fallback": "piglet.rgnets.com",
                "device_type": "wlanpi",
            },
        )

    def load(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(
                f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False
            )
            try:
                super().load()
            finally:
                run_command(
                    f"umount {self.data_part_path}", shell=True, use_shlex=False
                )

    def save(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(
                f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False
            )
            try:
                super().save()
            finally:
                run_command(
                    f"umount {self.data_part_path}", shell=True, use_shlex=False
                )

    def load_or_create_defaults(self):
        if self.count_partitions() < 3:
            self.logger.warning("Insufficient partitions--simulating instead.")
            self.data = self.simulate_config()
        else:
            run_command(
                f"mount {self.data_part_path} /mnt", shell=True, use_shlex=False
            )
            try:
                super().load_or_create_defaults()
            finally:
                run_command(
                    f"umount {self.data_part_path}", shell=True, use_shlex=False
                )

    def simulate_config(self) -> object:
        return copy.deepcopy(self.defaults)

    @staticmethod
    def count_partitions() -> int:
        return int(
            run_command(
                "ls -l /dev/mmcblk0p* | wc -l", shell=True, use_shlex=False
            ).stdout.strip()
        )


if __name__ == "__main__":
    boot = BootloaderConfigFile()
    boot.load()
    print(boot.data)
