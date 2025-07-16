import re
from typing import Any

from pydantic import BaseModel, Extra, Field, ValidationError
from datetime import datetime


class DHCPLeaseDate(BaseModel):
    value: datetime = Field()
    is_never: bool = Field(default=False)

    @classmethod
    def from_dhcp_date(cls, date_string: str) -> "DHCPLeaseDate":
        """
        Creates a DHCPLeaseDate instance from a date string from a dhclient lease file.
        """
        # The date is "never"
        if date_string.startswith("never"):
            return cls(is_never=True, value=datetime.now())

        # The date is an epoch timestamp.
        elif date_string.startswith("epoch"):
            match = re.search(r"expire\s+(?:epoch\s+)?([\d\/\s:]+);", date_string)
            if match:
                return cls(value=datetime.fromtimestamp(int(match.group(1).strip())))
            else:
                raise ValidationError(
                    "Date appears to be epoch but couldn't be parsed."
                )

        # The common date format is 'W YYYY/MM/DD HH:MM:SS', where W is the day of the week.
        # For example: '3 2024/07/17 10:30:00'
        return cls(value=datetime.strptime(date_string, "%w %Y/%m/%d %H:%M:%S"))


class DHCPOption(BaseModel):
    keyword: str = Field()
    data: str = Field()


class DHCPLease(BaseModel):
    fixed_address: str = Field()
    interface: str = Field()
    options: dict[str, DHCPOption] = Field(default_factory=dict)
    renew: DHCPLeaseDate = Field()
    rebind: DHCPLeaseDate = Field()
    expire: DHCPLeaseDate = Field()


class NetlinkEvent(BaseModel):
    type: str = Field()
    message: Any = Field()
