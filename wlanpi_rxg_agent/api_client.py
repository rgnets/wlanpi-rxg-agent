import logging
from os import PathLike
from typing import Optional, Union

import requests
import urllib3
from aiohttp import ClientResponse, ClientSession
from requests import Response
from structures import FlatResponse

from wlanpi_rxg_agent.utils import get_eth0_mac, get_interface_ip_addr


class ApiClient:

    def __init__(
        self,
        server_ip: Optional[str] = None,
        mac: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: Optional[int] = 15,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing ApiClient against {server_ip}")
        self.mac = mac or get_eth0_mac()
        self.registered = False
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.ip = server_ip
        self.api_base = "api"

        # Not the ideal way to silence this, but for now..
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    async def check_device(self, ip: Optional[str] = None) -> FlatResponse:
        if not ip:
            ip = self.ip
        async with ClientSession() as session:
            async with session.request(
                method="get",
                url=f"https://{ip}/{self.api_base}/apcert/check_device",
                params={"mac": self.mac, "device_type": "wlanpi"},
                verify_ssl=self.verify_ssl,
                timeout=self.timeout,
            ) as response:
                self.logger.debug(f"Returning response for tcpdump upload")
                # Returning a flat response here to make our lives easier. Do NOT return the raw ClientResponse object!
                # The async methods will not work outside the context providers above!
                # If you find yourself needing more data or in a different form, modify the
                # FlatResponse class to accommodate.
                # response._body = await response.read()
                content = await response.read()
                encoding = response.charset
                if not encoding:
                    try:
                        response.get_encoding()
                    except RuntimeError as e:
                        self.logger.error(f"Unable to determine encoding: {e}", exc_info=True)
                return FlatResponse(
                    headers=response.headers,
                    url=str(response.url),
                    status_code=response.status,
                    reason=response.reason,
                    content=content,
                    encoding= encoding,
                )

    async def get_cert(self, ip: Optional[str] = None) -> FlatResponse:
        if not ip:
            ip = self.ip
        async with ClientSession() as session:
            async with session.request(
                method="get",
                url=f"https://{ip}/{self.api_base}/apcert/get_cert",
                params={"mac": self.mac, "device_type": "wlanpi"},
                verify_ssl=self.verify_ssl,
                timeout=self.timeout,
            ) as response:
                self.logger.debug(f"Returning response for tcpdump upload")
                # Returning a flat response here to make our lives easier. Do NOT return the raw ClientResponse object!
                # The async methods will not work outside the context providers above!
                # If you find yourself needing more data or in a different form, modify the
                # FlatResponse class to accommodate.
                content = await response.read()
                encoding = response.charset
                if not encoding:
                    try:
                        response.get_encoding()
                    except RuntimeError as e:
                        self.logger.error(f"Unable to determine encoding: {e}", exc_info=True)
                return FlatResponse(
                    headers=response.headers,
                    url=str(response.url),
                    status_code=response.status,
                    reason=response.reason,
                    content=content,
                    encoding=encoding,
                )

    async def register(
        self,
        model: str,
        csr: str,
    ) -> FlatResponse:

        async with ClientSession() as session:
            async with session.request(
                method="post",
                url=f"https://{self.ip}/{self.api_base}/apcert/register",
                json={
                    "device_type": "wlanpi",
                    "mac": self.mac,
                    "csr": csr,
                    "model": model,
                    # "name": "Generic WLAN Pi",
                    "ip": get_interface_ip_addr("eth0"),
                },
                verify_ssl=self.verify_ssl,
                timeout=self.timeout,
            ) as response:
                self.logger.debug(f"Returning response for tcpdump upload")
                # Returning a flat response here to make our lives easier. Do NOT return the raw ClientResponse object!
                # The async methods will not work outside the context providers above!
                # If you find yourself needing more data or in a different form, modify the
                # FlatResponse class to accommodate.
                content = await response.read()
                encoding = response.charset
                if not encoding:
                    try:
                        response.get_encoding()
                    except RuntimeError as e:
                        self.logger.error(f"Unable to determine encoding: {e}", exc_info=True)
                return FlatResponse(
                    headers=response.headers,
                    url=str(response.url),
                    status_code=response.status,
                    reason=response.reason,
                    content=content,
                    encoding=encoding,
                )

    async def upload_tcpdump(
        self,
        file_path: Union[int, str, bytes, PathLike[str], PathLike[bytes]],
        submit_token: str,
        ip: Optional[str] = None,
    ) -> FlatResponse:
        if not ip:
            ip = self.ip
        files = {"file": open(file_path, "rb")}
        form_data = {"token": submit_token, "file": open(file_path, "rb")}
        async with ClientSession() as session:
            async with session.request(
                method="post",
                url=f"https://{ip}/{self.api_base}/tcpdumps/submit_tcpdump",
                data=form_data,
                verify_ssl=self.verify_ssl,
                timeout=self.timeout,
            ) as response:
                self.logger.debug(f"Returning response for tcpdump upload")
                # Returning a flat response here to make our lives easier. Do NOT return the raw ClientResponse object!
                # The async methods will not work outside the context providers above!
                # If you find yourself needing more data or in a different form, modify the
                # FlatResponse class to accommodate.
                content = await response.read()
                encoding = response.charset
                if not encoding:
                    try:
                        response.get_encoding()
                    except RuntimeError as e:
                        self.logger.error(f"Unable to determine encoding: {e}", exc_info=True)
                return FlatResponse(
                    headers=response.headers,
                    url=str(response.url),
                    status_code=response.status,
                    reason=response.reason,
                    content=content,
                    encoding=encoding,
                )
