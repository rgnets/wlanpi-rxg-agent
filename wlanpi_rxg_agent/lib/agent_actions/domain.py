from __future__ import annotations
import typing as t
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

class Data:

    class WifiConfigElement(BaseModel):
        id: t.Optional[int] = Field() #
        ssid: str = Field() #
        psk: str = Field() #
        encryption: t.Optional[str] = Field(default=None)
        authentication: t.Optional[str] = Field(default=None)

    class WifiConfiguration(BaseModel):
        interface: t.Optional[str] = Field(default=None)
        mode: str = Field()
        wlan: t.Optional[Data.WifiConfigElement] = Field()

    class PingTarget(BaseModel):
        id: int = Field() #                    :integer          not null, primary key
        count: int = Field(default=3) #              :integer

        interval: float = Field(default=1.0) #              :decimal(7, 2)    default(1.0)
        period: t.Optional[int] = Field(default=None, description="If specified, will schedule the ping to run periodically after the first attempt, in seconds.") #              :decimal(7, 2)    default(1.0)
        name: t.Optional[str] = Field(default=None) #                  :string
        note: t.Optional[str] = Field(default=None) #                  :text
        host: str = Field() #                :string
        timeout: float = Field() #               :decimal(4, 2)
        traceroute_interval: t.Optional[float] = Field(default=None) #   :decimal(7, 2)

        interface: t.Optional[str] = Field(default=None)
        ssid: t.Optional[str] = Field(default=None)
        psk: t.Optional[str] = Field(default=None)

    class Traceroute(BaseModel):
        id: int = Field()  # :integer          not null, primary key
        queries: int = Field(default=1, description="Queries per hop")
        period: t.Optional[int] = Field(default=None,
                                    description="If specified, will schedule the traceroute to run periodically after the first attempt, in seconds.")  #
        host: str = Field()  # :string
        interface: t.Optional[str] = Field(default=None)
        ssid: t.Optional[str] = Field(default=None)
        psk: t.Optional[str] = Field(default=None)


    class SpeedTest(BaseModel):
        id: int = Field()  # :integer          not null, primary key
        host: str = Field()  # :string
        port: int = Field()
        udp: bool = Field()

        period: t.Optional[int] = Field(default=None,
                                    description="If specified, will schedule the traceroute to run periodically after the first attempt, in seconds.")
        start_date: t.Optional[datetime] = Field(default_factory=datetime.now, description="The date and time when the speed test or test periods should start.")


        interface: t.Optional[str] = Field(default=None)
        ssid: t.Optional[str] = Field(default=None)
        psk: t.Optional[str] = Field(default=None)

class Messages:
    pass

class Commands:
    class Reboot(BaseModel):
        pass

    class SetRxgs(BaseModel):
        override: t.Optional[str] = Field(default=None)
        fallback: t.Optional[str] = Field(default=None)

    class SetCredentials(BaseModel):
        password: str = Field()
        user: str = Field(default="wlanpi")

    class ConfigureTraceroutes(BaseModel):
        pass

    class ConfigurePingTargets(BaseModel):
        targets: list[Data.PingTarget] = Field()

    class ConfigureAgent(BaseModel):
        wifi: dict[str, Data.WifiConfiguration] = Field(default={})
        ping_targets: list[Data.PingTarget] = Field(default=[])
        traceroute_targets: list[Data.Traceroute] = Field(default=[])
        speed_tests: list[Data.SpeedTest] = Field(default=[])

