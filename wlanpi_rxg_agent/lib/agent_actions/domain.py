import typing as t
from dataclasses import dataclass

class Messages:
    pass

class Commands:
    class Reboot(t.NamedTuple):
        pass

    @dataclass
    class SetRxgs:
        override: t.Optional[str] = None
        fallback: t.Optional[str] = None

    @dataclass
    class SetCredentials:
        password: str
        user: str = "wlanpi"
