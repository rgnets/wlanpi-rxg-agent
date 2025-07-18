import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from wlanpi_rxg_agent.lib.sip_control.custom_baresipy import CustomBaresipy
from wlanpi_rxg_agent.lib.sip_control.mdk_baresip import MdkBareSIP


class SipTest(ABC):
    @abstractmethod
    def __init__(
        self,
        gateway: str,
        user: str,
        password: str,
        extra_login_args: Optional[str] = None,
        debug: bool = False,
    ):
        pass

    @abstractmethod
    async def execute(
        self,
        callee: str,
        post_connect: Optional[str] = None,
        call_timeout: Optional[int] = None,
        summary_callback: Optional[Callable] = None,
    ):
        pass
