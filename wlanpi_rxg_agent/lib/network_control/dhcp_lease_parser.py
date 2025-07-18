import re
from pathlib import Path
from typing import Optional, Union

from .models import DHCPLease, DHCPLeaseDate, DHCPOption


class DHCPLeaseParser:
    def __init__(self, iface):
        self.lease_path = Path(f"/var/lib/dhcp/dhclient.{iface}.leases")

    def latest_lease(self) -> Optional[DHCPLease]:
        if not self.lease_path.exists():
            return None

        leases = self.lease_path.read_text().split("lease {")
        last = leases[-1]
        data: dict[str, Union[str, DHCPLeaseDate]] = {}

        options: dict[str, DHCPOption] = {}

        key_patterns = {
            "fixed-address": r"fixed-address\s+([\d\.]+);",
            "interface": r"interface\s+\"(\w+)\";",
            "renew": r"renew\s+((?:epoch\s+)?[\d\/\s:]+);",
            "rebind": r"rebind\s+((?:epoch\s+)?[\d\/\s:]+);",
            "expire": r"expire\s+((?:epoch\s+)?[\d\/\s:]+);",
        }

        for key, pattern in key_patterns.items():
            match = re.search(pattern, last)
            if match:
                data[key.replace("-", "_")] = match.group(1).strip()

        option_pattern = r"option ([\w-]+)\s+([\d\. ]+);"
        for line in last.split("\n"):
            match = re.search(option_pattern, line)
            if match:
                keyword = match.group(1).strip().replace("-", "_")
                options[keyword] = DHCPOption(
                    keyword=keyword, data=match.group(2).strip()
                )

        for date_key in ("renew", "rebind", "expire"):
            if date_key in data:
                data[date_key] = DHCPLeaseDate.from_dhcp_date(data[date_key])

        return DHCPLease(**data, options=options)

    # Example lease
    # lease {
    #   interface "wlan1";
    #   fixed-address 192.168.6.47;
    #   option subnet-mask 255.255.255.0;
    #   option routers 192.168.6.1;
    #   option dhcp-lease-time 86400;
    #   option dhcp-message-type 5;
    #   option domain-name-servers 192.168.6.1;
    #   option dhcp-server-identifier 192.168.6.1;
    #   option dhcp-renewal-time 39703;
    #   option broadcast-address 192.168.6.255;
    #   option dhcp-rebinding-time 72103;
    #   option host-name "wlanpi-c8b";
    #   option domain-name "gen.internal";
    #   renew 2 2025/07/15 23:12:28;
    #   rebind 3 2025/07/16 10:37:10;
    #   expire 3 2025/07/16 14:35:27;
    # }
