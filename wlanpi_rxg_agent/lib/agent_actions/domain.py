from __future__ import annotations
import typing as t
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, Extra

class Data:

    class WifiConfiguration(BaseModel):
        id: t.Optional[int] = Field() #
        ssid: str = Field() #
        psk: str = Field() #
        encryption: t.Optional[str] = Field(default=None)
        authentication: t.Optional[str] = Field(default=None)

    class RadioConfiguration(BaseModel):
        interface: t.Optional[str] = Field(default=None)
        mode: str = Field()
        wlan: t.Optional[Data.WifiConfiguration] = Field()

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
                                    description="If specified, will schedule the speed test to run periodically after the first attempt, in seconds.")
        start_date: t.Optional[datetime] = Field(default_factory=datetime.now, description="The date and time when the speed test or test periods should start.")


        interface: t.Optional[str] = Field(default=None)
        ssid: t.Optional[str] = Field(default=None)
        psk: t.Optional[str] = Field(default=None)


    class PingResponse(BaseModel):
        type: str = Field()
        timestamp: datetime = Field()
        bytes: int = Field()
        response_ip: str = Field()
        icmp_seq: int = Field()
        ttl: int = Field()
        time_ms: float = Field()
        duplicate: bool = Field()


    class CompletedPing(BaseModel):
        destination_ip: str = Field()
        interface: str = Field()
        data_bytes:  t.Any = Field(default=None)
        pattern:  t.Any = Field(default=None)
        destination: str = Field()
        packets_transmitted: int = Field()
        packets_received:  int = Field()
        packet_loss_percent:  float = Field()
        duplicates:  int = Field()
        time_ms:  float = Field()
        round_trip_ms_min:   float = Field()
        round_trip_ms_avg:   float = Field()
        round_trip_ms_max:    float = Field()
        round_trip_ms_stddev:    float = Field()
        jitter:  t.Optional[float] = Field(default=None)
        responses: list[Data.PingResponse] = Field(default=[])

    class TracerouteProbes(BaseModel):
        annotation: t.Any
        asn: t.Any
        ip: str = Field(examples=["8.8.4.4"])
        name: str = Field(examples=["syn-098-123-060-049.biz.spectrum.com"])
        rtt: float = Field(examples=["3.177"])

    class TracerouteHops(BaseModel):
        hop: int = Field(examples=[1], default=0)
        probes: list[Data.TracerouteProbes] = Field()

    class TracerouteResponse(BaseModel):
        destination_ip: str = Field(examples=["8.8.4.4"])
        destination_name: str = Field(examples=["dns.google.com"])
        hops: list[Data.TracerouteHops] = Field()

    class Iperf3ClientRequest(BaseModel):
        host: str = Field(examples=["192.168.1.1"])
        port: int = Field(examples=[5001], default=5001)
        time: int = Field(examples=[10], default=10)
        udp: bool = Field(default=False)
        reverse: bool = Field(default=False)
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)

    # No Iperf3Result yet as it hasn't been fully modeled and I (MDK) don't know what all potential output forms are in JSON mode.

    class Iperf2ClientRequest(BaseModel):
        host: str = Field(examples=["192.168.1.1"])
        port: int = Field(examples=[5001], default=5001)
        time: int = Field(examples=[10], default=10)
        udp: bool = Field(default=False)
        reverse: bool = Field(default=False)
        compatibility: bool = Field(default=False)
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)
        # version: int = Field(examples=[2, 3], default=3)
        # interface: t.Optional[str] = Field(examples=["eth0, wlan0"], default=None)
        # bind_address: t.Optional[str] = Field(examples=["192.168.1.12"], default=None)
        #
        # @model_validator(mode="after")
        # def check_dynamic_condition(self) -> Self:
        #     # print(self)
        #     if self.version not in [2, 3]:
        #         raise ValueError("iPerf version can be 2 or 3.")
        #     if self.bind_address is not None and self.interface is not None:
        #         raise ValueError("Only interface or bind_address can be specified.")
        #     return self

    class Iperf2Result(BaseModel, extra=Extra.allow):
        timestamp: int = Field()
        source_address: str = Field(examples=["192.168.1.5"])
        source_port: int = Field(examples=[5001])
        destination_address: str = Field(examples=["192.168.1.1"])
        destination_port: int = Field(examples=[12345])
        transfer_id: int = Field(examples=[3])
        interval: list[float] = Field(examples=[0.0, 10.0])
        transferred_bytes: int = Field()
        transferred_mbytes: float = Field()
        bps: int = Field()
        mbps: float = Field()
        jitter: t.Optional[float] = Field(default=None)
        error_count: t.Optional[int] = Field(default=None)
        datagrams: t.Optional[int] = Field(default=None)

    class Iperf2Test(Iperf2ClientRequest):
        id: int = Field()

    class Iperf3Test(Iperf3ClientRequest):
        id: int = Field()

    class DhcpTestResponse(BaseModel):
        time: float = Field()
        duid: str = Field(examples=["00:01:00:01:2e:74:ef:71:dc:a6:32:8e:04:17"])
        events: list[str] = Field()
        data: dict[str, str] = Field()

    class DhcpTestRequest(BaseModel):
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)
        timeout: int = Field(default=5)

    class DigRequest(BaseModel):
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)
        nameserver: t.Optional[str] = Field(examples=["wlan0"], default=None)
        host: str = Field(examples=["wlanpi.com"])

    class DigQuestion(BaseModel):
        name: str = Field(examples=["wlanpi.com."])
        question_class: str = Field(examples=["IN"], alias="class")
        type: str = Field(examples=["A"])

    class DigAnswer(BaseModel):
        name: str = Field(examples=["wlanpi.com."])
        answer_class: str = Field(examples=["IN"], alias="class")
        type: str = Field(examples=["A"])
        ttl: int = Field(examples=[1795])
        data: str = Field(examples=["165.227.111.100"])

    class DigResponse(BaseModel):
        id: int = Field()
        opcode: str = Field()
        status: str = Field()
        flags: list[str] = Field()
        query_num: int = Field()
        answer_num: int = Field()
        authority_num: int = Field()
        additional_num: int = Field()
        question: Data.DigQuestion = Field()
        answer: list[Data.DigAnswer] = Field()
        query_time: int = Field(examples=[3])
        server: str = Field(examples=["192.168.30.1#53(192.168.30.1)"])
        when: str = Field(examples=["Thu Nov 14 19:15:39 EST 2024"])
        rcvd: int = Field(examples=[82])


class Messages:

    class Message(BaseModel):
        pass

    class ExecutorCompleteMessage(Message):
        id: int = Field()
        error: t.Optional[str] = Field(default=None)
        result: t.Any = Field(default=None)
        extra: t.Any = Field(default=None)

    class PingBatchComplete(ExecutorCompleteMessage):
        result: t.Optional[Data.CompletedPing] = Field(default=None)

    class TracerouteComplete(ExecutorCompleteMessage):
        result: t.Optional[Data.TracerouteResponse] = Field(default=None)

    class Iperf2Complete(ExecutorCompleteMessage):
        result: t.Optional[Data.Iperf2Result] = Field(default=None)

    class Iperf3Complete(ExecutorCompleteMessage):
        result: t.Optional[t.Any] = Field(default=None)

    class DigTestComplete(ExecutorCompleteMessage):
        result: t.Optional[t.List[Data.DigResponse]] = Field(default=None)

    class DhcpTestComplete(ExecutorCompleteMessage):
        result: t.Optional[Data.DhcpTestResponse] = Field(default=None)


class Commands:
    class Reboot(BaseModel):
        pass

    class SetRxgs(BaseModel):
        override: t.Optional[str] = Field(default=None)
        fallback: t.Optional[str] = Field(default=None)

    class SetCredentials(BaseModel):
        password: str = Field()
        user: str = Field(default="wlanpi")

    class GetClients(BaseModel):
        pass

    class TCPDump(BaseModel):
        interface: str = Field()
        upload_token: str = Field()
        upload_ip: str = Field()
        max_packets: t.Optional[int] = Field(default=None)
        timeout: t.Optional[int] = Field(default=None)
        filter: t.Optional[str] = Field(default=None)

    class ConfigureRadios(BaseModel):
        interfaces: dict[str, Data.RadioConfiguration] = Field(default={})

    class ConfigureTraceroutes(BaseModel):
        targets: list[Data.Traceroute] = Field()

    class ConfigureSpeedTests(BaseModel):
        targets: list[Data.SpeedTest] = Field()

    class ConfigurePingTargets(BaseModel):
        targets: list[Data.PingTarget] = Field()

    class ConfigureAgent(BaseModel):
        wifi: dict[str, Data.RadioConfiguration] = Field(default={})
        ping_targets: list[Data.PingTarget] = Field(default=[])
        traceroute_targets: list[Data.Traceroute] = Field(default=[])
        speed_tests: list[Data.SpeedTest] = Field(default=[])

