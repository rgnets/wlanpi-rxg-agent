from __future__ import annotations

import typing as t
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Extra, Field


class Data:

    class WifiConfiguration(BaseModel):
        id: t.Optional[int] = Field()  #
        ssid: str = Field()  #
        psk: t.Optional[str] = Field()  #
        encryption: t.Optional[str] = Field(default=None)
        authentication: t.Optional[str] = Field(default=None)

    class RadioConfiguration(BaseModel):
        interface: t.Optional[str] = Field(default=None)
        # iface_mac: t.Optional[str] = Field(default=None)
        mode: str = Field()
        wlan: t.Optional[Data.WifiConfiguration] = Field()

    class TestBase(BaseModel):
        """Implements all the attributes that are required for scheduled tests"""

        id: int = Field()  # :integer          not null, primary key
        name: t.Optional[str] = Field(default=None)  #                  :string
        interval: float = Field(
            default=1.0
        )  #              :decimal(7, 2)    default(1.0)
        period: t.Optional[int] = Field(
            default=None,
            description="If specified, will schedule the ping to run periodically after the first attempt, in seconds.",
        )  #              :decimal(7, 2)    default(1.0)
        start_date: t.Optional[datetime] = Field(
            # default_factory=datetime.now,
            default=None,
            description="The date and time when the test should start.",
        )
        interface: t.Optional[str] = Field(default=None)
        ssid: t.Optional[str] = Field(default=None)
        psk: t.Optional[str] = Field(default=None)

        # iface_mac: t.Optional[str] = Field(default=None)
        # iface_vlan: t.Optional[int] = Field(default=None)

    class PingTarget(TestBase):
        count: int = Field(default=3)  #              :integer
        note: t.Optional[str] = Field(default=None)  #                  :text
        host: str = Field()  #                :string
        timeout: float = Field()  #               :decimal(4, 2)
        traceroute_interval: t.Optional[float] = Field(default=None)  #   :decimal(7, 2)

    class SpeedTest(TestBase):
        host: str = Field()  # :string
        port: int = Field()
        udp: bool = Field()

    class SipAccount(BaseModel, extra="ignore"):
        id: int = Field()
        name: t.Optional[str] = Field(default=None)
        host: str = Field()
        port: int = Field()
        user: str = Field()
        auth_user: str = Field()
        auth_pass: str = Field()
        transport: str = Field(default="udp")
        packet_time: t.Optional[int] = Field(default=None)
        registration_interval: t.Optional[int] = Field(default=3600)
        relative_wait: t.Optional[int] = Field(default=None)
        outbound: t.Optional[str] = Field(default=None)
        outbound2: t.Optional[str] = Field(default=None)
        extra: t.Optional[str] = Field(default=None)

    class SipTest(TestBase, extra="allow"):
        sip_account: Data.SipAccount = Field()
        callee: str = Field(alias="extension", alias_priority=0)
        post_connect: t.Optional[str] = Field()
        call_timeout: t.Optional[int] = Field(default=None)

    class SipTestRtcpSummary(BaseModel):
        reporter: str = Field(description="Reporter Identifier")
        call_setup_ms: int = Field(description="Call Setup in ms")
        call_duration_sec: int = Field(description="Call Duration in sec")
        rx_pkts: int = Field(description="Packets RX")
        tx_pkts: int = Field(description="Packets TX")
        tx_pkts_lost: int = Field(description="Packets Lost TX")
        rx_pkts_lost: int = Field(description="Packets Lost RX")
        tx_pkts_discarded: int = Field(description="Packets Discarded, TX")
        rx_pkts_discarded: int = Field(description="Packets Discarded, RX ")
        tx_jitter: float = Field(description="Jitter TX in ms")
        rx_jitter: float = Field(description="Jitter RX in ms")
        rtt: float = Field(description="RTT in ms")
        local_ip: str = Field(description="Local IP")
        remote_ip: str = Field(description="Remote IP")
        mos_score: float = Field(
            description="Mean Opinion Score, as calculated by reporter"
        )

        @staticmethod
        def from_baresip_summary(summary: dict[str, str]):
            return Data.SipTestRtcpSummary(
                reporter=str(summary["EX"]),
                call_setup_ms=int(summary["CS"]),
                call_duration_sec=int(summary["CD"]),
                tx_pkts=int(summary["PS"]),
                rx_pkts=int(summary["PR"]),
                tx_pkts_lost=int(summary["PL"].split(",")[1]),
                rx_pkts_lost=int(summary["PL"].split(",")[0]),
                tx_pkts_discarded=int(summary["PD"].split(",")[1]),
                rx_pkts_discarded=int(summary["PD"].split(",")[0]),
                tx_jitter=float(summary["JI"].split(",")[1]),
                rx_jitter=float(summary["JI"].split(",")[0]),
                rtt=float(summary["DL"]),
                local_ip=str(summary["IP"].split(",")[0]),
                remote_ip=str(summary["IP"].split(",")[1]),
                mos_score=float(summary["MOS"]),
            )

    # Ping
    class PingRequest(BaseModel):
        host: str = Field(examples=["google.com", "192.168.1.1"])
        count: int = Field(
            examples=[1, 10], description="How many packets to send.", default=1
        )
        interval: float = Field(
            examples=[1],
            description="The interval between packets, in seconds",
            default=1,
        )
        ttl: t.Optional[int] = Field(
            examples=[20],
            description="The Time-to-Live of the ping attempt.",
            default=None,
        )
        interface: t.Optional[str] = Field(
            examples=["eth0"],
            description="The interface the ping should originate from",
            default=None,
        )
        # iface_mac: t.Optional[str] = Field(default=None)
        # iface_vlan: t.Optional[int] = Field(default=None)

    class PingResponse(BaseModel):
        type: str = Field()
        timestamp: datetime = Field()
        bytes: int = Field()
        response_ip: str = Field()
        icmp_seq: int = Field()
        ttl: int = Field()
        time_ms: float = Field()
        duplicate: bool = Field()

    class PingResult(
        BaseModel,
    ):
        destination_ip: str = Field(examples=["142.250.190.142"])
        interface: t.Optional[str] = Field(
            examples=["eth0"],
            default=None,
            description="The interface the user specified that the ping be issued from. It will be empty if there wasn't one specified.",
        )
        data_bytes: t.Optional[int] = Field(examples=[56], default=None)
        pattern: t.Optional[str] = Field(default=None)
        destination: str = Field(examples=["google.com"])
        packets_transmitted: int = Field(examples=[10])
        packets_received: int = Field(examples=[10])
        packet_loss_percent: float = Field(examples=[0.0])
        duplicates: int = Field(examples=[0])
        time_ms: float = Field(examples=[9012.0])
        round_trip_ms_min: t.Optional[float] = Field(examples=[24.108], default=None)
        round_trip_ms_avg: t.Optional[float] = Field(examples=[29.318], default=None)
        round_trip_ms_max: t.Optional[float] = Field(examples=[37.001], default=None)
        round_trip_ms_stddev: t.Optional[float] = Field(examples=[4.496], default=None)
        jitter: t.Optional[float] = Field(examples=[37.001], default=None)
        responses: list[Data.PingResponse] = Field()

    class PingFailure(BaseModel):
        destination: str = Field(examples=["google.com"])
        message: str = Field(examples=["No route to host"])

    class CompletedPing(BaseModel):
        destination_ip: str = Field()
        interface: str = Field()
        data_bytes: t.Any = Field(default=None)
        pattern: t.Any = Field(default=None)
        destination: str = Field()
        packets_transmitted: int = Field()
        packets_received: int = Field()
        packet_loss_percent: float = Field()
        duplicates: int = Field()
        time_ms: float = Field()
        round_trip_ms_min: float = Field()
        round_trip_ms_avg: float = Field()
        round_trip_ms_max: float = Field()
        round_trip_ms_stddev: float = Field()
        jitter: t.Optional[float] = Field(default=None)
        responses: list[Data.PingResponse] = Field(default=[])

    class Iperf3ClientRequest(BaseModel):
        host: str = Field(examples=["192.168.1.1"])
        port: int = Field(examples=[5001], default=5001)
        time: int = Field(examples=[10], default=10)
        udp: bool = Field(default=False)
        reverse: bool = Field(default=False)
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)

    #  Iperf3Result hasn't been fully modeled and I (MDK) don't know what all potential output forms are in JSON mode.

    class Iperf3Result(BaseModel, extra="allow"):
        end: dict[str, t.Any] = Field()
        start: dict[str, t.Any] = Field()
        intervals: list[dict[str, t.Any]] = Field()

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

    class Traceroute(TestBase):
        queries: int = Field(default=1, description="Queries per hop")
        period: t.Optional[int] = Field(
            default=None,
            description="If specified, will schedule the traceroute to run periodically after the first attempt, in seconds.",
        )  #
        host: str = Field()  # :string

    # Traceroute
    # Most of these reflect the API definitions in Core
    class TracerouteRequest(BaseModel):
        host: str = Field(examples=["dns.google.com"])
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)
        bypass_routing: bool = Field(default=False)
        queries: t.Optional[int] = Field(default=3)
        max_ttl: t.Optional[int] = Field(default=30)

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

    # DHCP Test

    class DhcpTestResponse(BaseModel):
        time: float = Field()
        duid: str = Field(examples=["00:01:00:01:2e:74:ef:71:dc:a6:32:8e:04:17"])
        events: list[str] = Field()
        data: dict[str, str] = Field()

    class DhcpTestRequest(BaseModel):
        interface: t.Optional[str] = Field(examples=["wlan0"], default=None)
        timeout: int = Field(default=5)

    # Dig Test

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

    class TestCompleteMessage(Message):
        id: t.Optional[int] = Field(default=None)
        error: t.Optional[str] = Field(default=None)
        result: t.Any = Field(default=None)
        extra: t.Any = Field(default=None)
        request: t.Any = Field(default=None)

    # Reflect the Core definitions above, so we can modify the messages here

    class PingResult(Data.PingResult):
        pass

    class PingFailure(Data.PingFailure):
        pass

    class PingComplete(TestCompleteMessage):
        result: t.Union[Data.PingResult, Data.PingFailure] = Field()
        request: Data.PingRequest = Field()

    class TracerouteResponse(Data.TracerouteResponse):
        pass

    class TracerouteComplete(TestCompleteMessage):
        result: t.Optional[Data.TracerouteResponse] = Field(default=None)
        request: Data.TracerouteRequest = Field()

    class Iperf2Result(Data.Iperf2Result):
        pass

    class Iperf2Complete(TestCompleteMessage):
        result: t.Optional[Data.Iperf2Result] = Field(default=None)
        request: Data.Iperf2ClientRequest = Field()

    class Iperf3Result(Data.Iperf3Result, extra="allow"):
        pass

    class Iperf3Complete(TestCompleteMessage):
        result: t.Optional[t.Any] = Field(default=None)
        request: Data.Iperf3ClientRequest = Field()

    class DigResponse(Data.DigResponse):
        pass

    class DigTestComplete(TestCompleteMessage):
        result: t.Optional[t.List[Data.DigResponse]] = Field(default=None)
        request: Data.DigRequest = Field()

    class DhcpTestResponse(Data.DhcpTestResponse):
        pass

    class DhcpTestComplete(TestCompleteMessage):
        result: t.Optional[Data.DhcpTestResponse] = Field(default=None)
        request: Data.DhcpTestRequest = Field()

    class SipTestComplete(TestCompleteMessage):
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

    class ConfigureTestBase(BaseModel):
        targets: list[Data.Traceroute] = Field()

    class ConfigureTraceroutes(BaseModel):
        targets: list[Data.Traceroute] = Field()

    class ConfigureSpeedTests(BaseModel):
        targets: list[Data.SpeedTest] = Field()

    class ConfigurePingTargets(BaseModel):
        targets: list[Data.PingTarget] = Field()

    class ConfigureSipTests(BaseModel):
        targets: list[Data.SipTest] = Field()

    class ConfigureAgent(BaseModel):
        wifi: dict[str, Data.RadioConfiguration] = Field(default={})
        ping_targets: list[Data.PingTarget] = Field(default=[])
        traceroute_targets: list[Data.Traceroute] = Field(default=[])
        speed_tests: list[Data.SpeedTest] = Field(default=[])
        sip_tests: list[Data.SipTest] = Field(default=[])

    class Ping(Data.PingRequest):
        pass

    class Traceroute(Data.TracerouteRequest):
        pass

    class Iperf2(Data.Iperf2ClientRequest):
        pass

    class Iperf3(Data.Iperf3ClientRequest):
        pass

    class Dig(Data.DigRequest):
        pass

    class DhcpTest(Data.DhcpTestRequest):
        pass

    class SipTest(Data.SipTest):
        pass
