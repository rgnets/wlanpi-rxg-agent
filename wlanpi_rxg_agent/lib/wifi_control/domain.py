import typing as t
from dataclasses import dataclass

class Messages:
    pass

class Commands:
    # class Reboot(t.NamedTuple):
    #     pass

    @dataclass
    class GetOrCreateInterface:
        if_name: str
