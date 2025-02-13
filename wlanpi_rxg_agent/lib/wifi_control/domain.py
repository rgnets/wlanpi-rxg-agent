import typing as t
from dataclasses import dataclass

class Messages:

    @dataclass
    class WifiControlEvent:
        interface: str


    @dataclass
    class DhcpRenewing(WifiControlEvent):
        pass

    @dataclass
    class DhcpRenewalFailed(WifiControlEvent):
        message: t.Optional[str]
        exc: t.Optional[Exception]

    @dataclass
    class DhcpRenewed(WifiControlEvent):
        pass

    @dataclass
    class WpaSupplicantEvent(WifiControlEvent):
        details: dict #= field(default_factory=dict)

    @dataclass
    class WpaSupplicantStateChanged(WpaSupplicantEvent):
        state: str
    #
    # @dataclass
    # class Disconnected(WpaSupplicantStateChanged):
    #     state="disconnected"
    #
    # @dataclass
    # class InterfaceDisabled(WpaSupplicantStateChanged):
    #     state="interface_disabled"
    #
    # @dataclass
    # class Inactive(WpaSupplicantStateChanged):
    #     state="inactive"
    #
    # @dataclass
    # class Scanning(WpaSupplicantStateChanged):
    #     state="scanning"
    #
    # @dataclass
    # class Authenticating(WpaSupplicantStateChanged):
    #     state="authenticating"
    #
    # @dataclass
    # class Associating(WpaSupplicantStateChanged):
    #     state="associating"
    #
    # @dataclass
    # class Associated(WpaSupplicantStateChanged):
    #     state="associated"
    #
    # @dataclass
    # class FourWayHandshake(WpaSupplicantStateChanged):
    #     state="4-way handshake" # Todo: Verify this is the correct way to do this
    #
    # @dataclass
    # class GroupHandshake(WpaSupplicantStateChanged):
    #     state="group handshake" # Todo: Verify this is the correct way to do this
    #
    # @dataclass
    # class Completed(WpaSupplicantStateChanged):
    #     state="completed"



    @dataclass
    class ScanningStateChanged(WpaSupplicantEvent):
        scanning: bool


    @dataclass
    class Disconnection(WpaSupplicantEvent):
        pass




    @dataclass
    class WpaSupplicantScanResults:
        interface: str
        results: list


class Commands:
    # class Reboot(t.NamedTuple):
    #     pass


    @dataclass
    class GetOrCreateInterface:
        if_name: str
