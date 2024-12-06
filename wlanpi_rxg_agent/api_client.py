from typing import Optional

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
        timeout: int = 15,
    ):
        self.mac = mac or get_eth0_mac()
        self.registered = False
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.ip = server_ip
        self.api_base = "api/apcert"

        # Not the ideal way to silence this, but for now..
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def check_device(self, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        return requests.get(
            url=f"https://{ip}/{self.api_base}/check_device",
            params={"mac": self.mac, "device_type": "wlanpi"},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def get_cert(self, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        return requests.get(
            url=f"https://{ip}/{self.api_base}/get_cert",
            params={"mac": self.mac, "device_type": "wlanpi"},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def register(self, model: str, csr: str, ip: Optional[str] = None) -> Response:
        if not ip:
            ip = self.ip
        return requests.post(
            url=f"https://{ip}/{self.api_base}/register",
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
