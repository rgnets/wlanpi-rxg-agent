from os import PathLike
from typing import Optional, Union

import requests
import urllib3
from requests import Response

from wlanpi_rxg_agent.utils import get_eth0_mac, get_interface_ip_addr


class ApiClient:

    def __init__(
        self,
        server_ip: Optional[str] = None,
        mac: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: Optional[int] = 15,
    ):
        self.mac = mac or get_eth0_mac()
        self.registered = False
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.ip = server_ip
        self.api_base = "api"

        # Not the ideal way to silence this, but for now..
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def check_device(self, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        return requests.get(
            url=f"https://{ip}/{self.api_base}/apcert/check_device",
            params={"mac": self.mac, "device_type": "wlanpi"},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def get_cert(self, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        return requests.get(
            url=f"https://{ip}/{self.api_base}/apcert/get_cert",
            params={"mac": self.mac, "device_type": "wlanpi"},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def register(self, model: str, csr: str, ) -> Response:
        if not ip:
            ip = self.ip
        return requests.post(
            url=f"https://{ip}/{self.api_base}/apcert/register",
            json={
                "device_type": "wlanpi",
                "mac": self.mac,
                "csr": csr,
                "model": model,
                # "name": "Generic WLAN Pi",
                "ip": get_interface_ip_addr("eth0"),
            },
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    async def upload_tcpdump(self, file_path:Union[int, str, bytes, PathLike[str], PathLike[bytes]], submit_token:str, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        files = {'file': open(file_path, 'rb')}
        form_data = {'token': submit_token}
        return requests.post(
            url=f"https://{ip}/{self.api_base}/tcpdumps/submit_tcpdump",
            data=form_data,
            files=files,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
