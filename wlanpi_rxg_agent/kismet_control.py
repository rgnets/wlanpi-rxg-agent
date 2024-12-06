import logging
import pprint
import random
import re
import string

import os
import subprocess
import time
from typing import Optional, Any
import dpkt
import kismet_rest  # type: ignore
import time

from scapy.data import DLT_IEEE802_11, DLT_EN10MB
from scapy.layers.dot11 import Dot11
from scapy.utils import PcapReader, PcapWriter, PcapNgReader, PcapNgWriter
import kismet_capture
from models.runcommand_error import RunCommandError
from utils import run_command


class KismetControlException(Exception):
    pass


class KismetControl:

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing KismetControl")
        self.__kismet_httpd_conf_file = os.path.expanduser("~/.kismet/kismet_httpd.conf")

        self.kismet_config = self.load_kismet_config()
        self.kismet_conn = kismet_rest.KismetConnector(
            username=self.kismet_config["httpd_username"],
            password=self.kismet_config["httpd_password"]
        )
        self.kismet_devices = kismet_rest.Devices(
            username=self.kismet_config["httpd_username"],
            password=self.kismet_config["httpd_password"])
        self.kismet_sources = kismet_rest.Datasources(
            username=self.kismet_config["httpd_username"],
            password=self.kismet_config["httpd_password"])
        self.kismet_alerts = kismet_rest.Alerts(
            username=self.kismet_config["httpd_username"],
            password=self.kismet_config["httpd_password"])
        self.kismet_capture = kismet_capture.KismetCapture(
            username=self.kismet_config["httpd_username"],
            password=self.kismet_config["httpd_password"])

    def read_kismet_config(self) -> dict[str, str]:
        """
        :raises: FileNotFoundError
        :return: 
        """
        out_dict = {}
        with open(self.__kismet_httpd_conf_file, "r") as f:
            for line in f:
                if "=" in line:
                    key, val = line.split("=", 1)
                    out_dict[key] = val.strip()
        return out_dict

    def write_new_kismet_config(self) -> dict[str, str]:
        contents = {
            "httpd_password": self.generate_random_password(20),
            "httpd_username": "wlanpi"
        }

        # Ensure directory exists before writing the file
        os.makedirs(os.path.dirname(self.__kismet_httpd_conf_file), exist_ok=True)
        with open(self.__kismet_httpd_conf_file, "w") as f:
            for key, value in contents.items():
                f.write(f"{key}={value}\n")
        return contents

    def load_kismet_config(self) -> dict[str, str]:
        try:
            config = self.read_kismet_config()
            if config:
                return config
            return self.write_new_kismet_config()
        except FileNotFoundError:
            return self.write_new_kismet_config()

    @staticmethod
    def generate_random_password(length=12):
        """
        Generates a random password with the given length.

        :param length: The length of the password to generate.
        :return: A random password string.
        """
        if length < 4:  # Ensure the password has a decent length
            raise ValueError("Password length should be at least 4 characters.")

        # Define potential password characters
        all_chars = string.ascii_letters + string.digits + string.punctuation

        # Generate a random password
        password = ''.join(random.choice(all_chars) for _ in range(length))

        return password

    @staticmethod
    def find_kismet_pid() -> Optional[int]:
        try:
            return int(run_command("pidof kismet").stdout.strip())
        except Exception as e:
            return None

    @staticmethod
    def is_kismet_running() -> bool:
        if KismetControl.find_kismet_pid():
            return True
        else:
            return False

    def start_kismet(self, source: str):
        if not self.is_kismet_running():
            subprocess.run(["kismet", "--daemonize", "-n", "-c", source])
            # run_command(["kismet", "--daemonize", "-n", "-c", source], timeout=3)
            # Todo: Do fancier things here to wait until server is up and responsive.
            time.sleep(2)

    def kill_kismet(self):
        if self.is_kismet_running():
            run_command(["killall", "-9", "kismet"])

    # Methods to be used after Kismet is running

    # Source management
    def available_kismet_interfaces(self) -> dict[str, dict[str, Any]]:
        return {x['kismet.datasource.probed.interface']: x for x in self.kismet_sources.interfaces() if
                not x['kismet.datasource.probed.interface'].endswith('mon')}

    def active_kismet_interfaces(self) -> dict[str, str]:
        return {x['kismet.datasource.probed.interface']: x['kismet.datasource.probed.in_use_uuid']
                for x in self.kismet_sources.interfaces()
                if x['kismet.datasource.probed.in_use_uuid'] != '00000000-0000-0000-0000-000000000000'
                and not x['kismet.datasource.probed.interface'].endswith('mon')}

    def source_uuid_to_name(self, source_uuid, interfaces: Optional[list[Any]] = None) -> Optional[str]:
        if interfaces is None:
            interfaces = list(self.available_kismet_interfaces().values())
        for x in interfaces:
            if x['kismet.datasource.probed.in_use_uuid'] == source_uuid and x[
                'kismet.datasource.probed.in_use_uuid'] != '00000000-0000-0000-0000-000000000000':
                return x['kismet.datasource.probed.interface']
        return None

    def get_kismet_interface_uuid(self, interface: str) -> Optional[str]:
        for x in self.kismet_sources.interfaces():
            if x['kismet.datasource.probed.interface'] == interface:
                return x['kismet.datasource.probed.in_use_uuid']
        return None

    def add_source(self, source_name: str) -> bool:
        return self.kismet_sources.add(source=source_name)

    def close_source(self, source_uuid: str) -> bool:
        return self.kismet_sources.close(source_uuid)

    def close_source_by_name(self, source_name: str) -> bool:
        for x in self.kismet_sources.interfaces():
            if x['kismet.datasource.probed.interface'] == source_name:
                return self.close_source(x['kismet.datasource.probed.in_use_uuid'])
        return False

    def set_sources_by_name(self, source_names: list[str]) -> list[tuple[str, str, bool]]:
        results = []
        # Remove other sources that aren't in the list
        for source_name, source_uuid in self.active_kismet_interfaces().items():

            if source_uuid not in source_names:
                results.append(('remove', source_name, self.close_source_by_name(source_name)))

        for source_name in source_names:
            if source_name not in self.active_kismet_interfaces():
                results.append(('add', source_name, self.add_source(source_name)))
        return results

    # Todo: May need to define hopping behavior somewhere. I think the defaults are sane for now.

    # Calls for metrics
    # def get_seen_clients(self):

    def get_seen_aps(self):
        fields_of_interest = [
            'kismet.device.base.seenby',
            'kismet.device.base.name',
            'kismet.device.base.freq_khz_map',
            'kismet.device.base.macaddr',
            'kismet.device.base.manuf',
            'kismet.device.base.channel',
            'kismet.device.base.frequency',
            'kismet.device.base.key',
            'kismet.device.base.signal',
            'kismet.device.base.type'
            # 'dot11.device'
        ]
        current_avail_interfaces = list(self.available_kismet_interfaces().values())
        results = []
        for ap in self.kismet_devices.dot11_access_points(fields=fields_of_interest):

            seen_by = []
            for seer in ap['kismet.device.base.seenby']:
                # seen_by.append(self.source_uuid_to_name(seer, interfaces=current_avail_interfaces))
                new_seer = {key.lstrip("kismet.common.seenby."): value for key, value in seer.items()}
                new_seer['interface'] = self.source_uuid_to_name(new_seer['uuid'], interfaces=current_avail_interfaces)
                seen_by.append(new_seer)
            if 'kismet.device.base.signal' in ap:
                signal = {key.lstrip("kismet.common.signal."): value for key, value in
                          ap['kismet.device.base.signal'].items()}
            else:
                signal = None

            # del seen_by['uuid']
            results.append({
                'key': ap['kismet.device.base.key'],
                'type': ap['kismet.device.base.type'],
                'ssid': ap['kismet.device.base.name'],
                'mac': ap['kismet.device.base.macaddr'],
                'freq': ap['kismet.device.base.frequency'],
                'channel': ap['kismet.device.base.channel'],
                'freq_mhz': ap['kismet.device.base.frequency'] / 1000,
                # 'seen_by': ap['kismet.device.base.seenby'],
                'seen_by': seen_by,
                'signal': signal,

                # 'dot11.device': ap['dot11.device']
            })
        return results

    @staticmethod
    def empty_seen_devices():
        return {"Wi-Fi Client": [], "Wi-Fi AP": [], "Wi-Fi Ad-Hoc": [], "Wi-Fi Bridged": [], "Wi-Fi Device": []}

    def get_seen_devices(self):
        # "kismet.device.base.type": "Wi-Fi Client",
        fields_of_interest = [
            'kismet.device.base.seenby',
            'kismet.device.base.name',
            'kismet.device.base.freq_khz_map',
            'kismet.device.base.macaddr',
            'kismet.device.base.manuf',
            'kismet.device.base.channel',
            'kismet.device.base.frequency',
            'kismet.device.base.key',
            'kismet.device.base.signal',
            'kismet.device.base.type'
            'dot11.device'
            # 'dot11.device.last_bssid'
        ]

        res = KismetControl.empty_seen_devices()
        current_avail_interfaces = list(self.available_kismet_interfaces().values())

        # Clients,Bridges, and Devices have client maps
        for device in self.kismet_devices.all():
            # print(device["kismet.device.base.commonname"])
            base_type = device['kismet.device.base.type']
            seen_by = []

            for seer in device['kismet.device.base.seenby']:
                # seen_by.append(self.source_uuid_to_name(seer, interfaces=current_avail_interfaces))
                new_seer = {key.lstrip("kismet.common.seenby."): value for key, value in seer.items()}
                new_seer['interface'] = self.source_uuid_to_name(new_seer['uuid'], interfaces=current_avail_interfaces)
                seen_by.append(new_seer)
            if 'kismet.device.base.signal' in device:
                signal = {re.sub(r"^kismet\.common\.signal\.", "", key): value for key, value in
                          device['kismet.device.base.signal'].items()}
            else:
                signal = None

            prepared_device = {
                'key': device['kismet.device.base.key'],
                'type': device['kismet.device.base.type'],
                'ssid': device['kismet.device.base.name'],
                'mac': device['kismet.device.base.macaddr'],
                'freq': device['kismet.device.base.frequency'],
                'channel': device['kismet.device.base.channel'],
                'freq_mhz': device['kismet.device.base.frequency'] / 1000,
                # 'seen_by': device['kismet.device.base.seenby'],
                'seen_by': seen_by,
                'signal': signal,

                # 'dot11.device': ap['dot11.device']
            }

            if base_type in ["Wi-Fi Client"]:
                if device['dot11.device'] and 'dot11.device.last_bssid' in device['dot11.device']:
                    prepared_device['last_bssid'] = device['dot11.device']["dot11.device.last_bssid"]
                else:
                    prepared_device['last_bssid'] = None

            try:
                res[base_type].append(prepared_device)
            except KeyError:
                res[base_type] = [prepared_device]
            # if device['kismet.device.base.type'] == 'Wi-Fi Client':
            #     res[device['kismet.device.base.key']] = device['kismet.device.base.seenby']

        return res
    #
    # def test_method(self):
    #     res = {"Wi-Fi Client": [], "Wi-Fi AP": [], "Wi-Fi Ad-Hoc": [], "Wi-Fi Bridged": [], "Wi-Fi Device": []}
    #
    #     # Clients,Bridges, and Devices have client maps
    #     for device in self.kismet_devices.all():
    #         print(device["kismet.device.base.commonname"])
    #         base_type = device['kismet.device.base.type']
    #         try:
    #             res[base_type].append(device)
    #         except KeyError:
    #             res[base_type] = [device]
    #         # if device['kismet.device.base.type'] == 'Wi-Fi Client':
    #         #     res[device['kismet.device.base.key']] = device['kismet.device.base.seenby']
    #
    #     return res
    #
    # def capture_from_datasource(self, datasource_uuid, timeout:Optional[int]=None, max_packets:Optional[int]=None):
    #     # 5FE308BD-0000-0000-0000-E0E1A9389BC7
    #     # http://{{device}}:{{kismet_port}}/datasource/pcap/by-uuid/{{datasource_uuid}}/packets.pcapng
    #     self.logger.info(f"Capturing from datasource {datasource_uuid}")
    #     response = self.kismet_capture.capture_by_uuid(datasource_uuid)
    #
    #     self.logger.debug("Starting capture generator.")
    #     start_time = time.monotonic()
    #     packet_count = 0
    #     # d = PcapReader(response.raw)
    #
    #     with PcapReader(response.raw) as pcap_fd:
    #         # self.logger.debug(f"reader link type: {pcap_fd.dlt}")
    #         for ts, packet in pcap_fd:
    #             self.logger.debug(f"New packet! Summary: {packet.summary()}")
    #             packet_count+=1
    #             yield ts, packet
    #             elapsed_time = time.monotonic() - start_time  # calculate how much time has passed
    #             if timeout is not None and elapsed_time >= timeout:  # 5 second timeout
    #                 self.logger.debug("Timeout reached. Stopping capture.")
    #                 response.close()
    #                 break
    #
    #             if max_packets is not None and packet_count >= max_packets:
    #                 self.logger.debug(f"Max packets reached ({max_packets}). Stopping capture.")
    #                 response.close()
    #                 break
    #
    # def capture_from_datasource_dpkt(self, datasource_uuid, timeout:Optional[int]=None, max_packets:Optional[int]=None):
    #     # 5FE308BD-0000-0000-0000-E0E1A9389BC7
    #     # http://{{device}}:{{kismet_port}}/datasource/pcap/by-uuid/{{datasource_uuid}}/packets.pcapng
    #     self.logger.info(f"Capturing from datasource {datasource_uuid}")
    #     response = self.kismet_capture.capture_by_uuid(datasource_uuid)
    #
    #     self.logger.debug("Starting capture generator.")
    #     start_time = time.monotonic()
    #     packet_count = 0
    #     # d = PcapReader(response.raw)
    #
    #     with response.raw as pcap_fd:
    #         reader = dpkt.pcapng.Reader(pcap_fd)
    #         # self.logger.debug(f"reader link type: {pcap_fd.dlt}")
    #         for ts, packet in reader:
    #             self.logger.debug(f"New packet! Summary:")
    #             packet_count+=1
    #             yield ts, packet
    #             elapsed_time = time.monotonic() - start_time  # calculate how much time has passed
    #             if timeout is not None and elapsed_time >= timeout:  # 5 second timeout
    #                 self.logger.debug("Timeout reached. Stopping capture.")
    #                 response.close()
    #                 break
    #
    #             if max_packets is not None and packet_count >= max_packets:
    #                 self.logger.debug(f"Max packets reached ({max_packets}). Stopping capture.")
    #                 response.close()
    #                 break

if __name__ == "__main__":
    # logger = logging.getLogger(__name__)
    # logging.basicConfig(encoding="utf-8", level=logging.INFO)
    # kc = KismetControl()
    #
    # # with PcapWriter('/tmp/output.pcapng', linktype=DLT_EN10MB, append=False) as fd:
    # # with PcapWriter('/tmp/output.pcapng', linktype=DLT_IEEE802_11, append=False) as fd:
    # # with PcapWriter('/tmp/output.pcapng', append=False) as fd:
    # with open('/tmp/output.pcapng', 'wb') as fd:
    #     writer = dpkt.pcapng.Writer(fd)
    #     for ts, packet in kc.capture_from_datasource_dpkt(datasource_uuid="5FE308BD-0000-0000-0000-E0E1A9389BC7",
    #                                              max_packets=10):
    #         # pprint.pp(packet.summary())
    #         writer.writepkt(packet, ts)

    print("Done")
    # for device in kc.kismet_conn.device_summary():
    #     pprint.pprint(device)
