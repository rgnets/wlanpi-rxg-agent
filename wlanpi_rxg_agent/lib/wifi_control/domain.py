import typing as t
from dataclasses import dataclass
from pydantic import BaseModel, Field


class Messages:

    class WifiControlEvent(BaseModel):
        interface: str = Field()

    class DhcpRenewing(WifiControlEvent):
        pass

    class DhcpRenewalFailed(WifiControlEvent):
        message: t.Optional[str] = Field()
        exc: t.Optional[Exception] = Field()

        class Config:
            arbitrary_types_allowed = True

    class DhcpRenewed(WifiControlEvent):
        pass

    class WpaSupplicantEvent(WifiControlEvent):
        details: dict[str, t.Any] = Field(default_factory=dict)

    class WpaSupplicantStateChanged(WpaSupplicantEvent):
        state: str = Field()

    #

    # class Disconnected(WpaSupplicantStateChanged):
    #     state="disconnected"
    #

    # class InterfaceDisabled(WpaSupplicantStateChanged):
    #     state="interface_disabled"
    #

    # class Inactive(WpaSupplicantStateChanged):
    #     state="inactive"
    #

    # class Scanning(WpaSupplicantStateChanged):
    #     state="scanning"
    #

    # class Authenticating(WpaSupplicantStateChanged):
    #     state="authenticating"
    #

    # class Associating(WpaSupplicantStateChanged):
    #     state="associating"
    #

    # class Associated(WpaSupplicantStateChanged):
    #     state="associated"
    #

    # class FourWayHandshake(WpaSupplicantStateChanged):
    #     state="4-way handshake" # Todo: Verify this is the correct way to do this
    #

    # class GroupHandshake(WpaSupplicantStateChanged):
    #     state="group handshake" # Todo: Verify this is the correct way to do this
    #

    # class Completed(WpaSupplicantStateChanged):
    #     state="completed"

    class ScanningStateChanged(WpaSupplicantEvent):
        scanning: bool = Field()

    class Disconnection(WpaSupplicantEvent):
        pass

    # Not used yet, to be better defined later.
    class WpaSupplicantScanResults:
        interface: str = Field()

        results: list[t.Any] = Field()


class Commands:
    # class Reboot(t.NamedTuple):
    #     pass

    class GetOrCreateInterface(BaseModel):
        if_name: str = Field()
