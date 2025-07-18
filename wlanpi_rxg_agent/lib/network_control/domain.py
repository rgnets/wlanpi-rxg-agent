import typing as t
from enum import Enum
from ipaddress import IPv4Address, IPv4Interface
from typing import Optional

from pydantic import BaseModel, Field


class InterfaceState(Enum):
    """Network interface states"""

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class InterfaceType(Enum):
    """Network interface types"""

    WIRELESS = "wireless"
    ETHERNET = "ethernet"
    LOOPBACK = "loopback"
    OTHER = "other"


class InterfaceInfo(BaseModel):
    """Information about a network interface"""

    name: str = Field(..., description="Interface name (e.g., wlan0)")
    index: int = Field(..., description="Interface index")
    state: InterfaceState = Field(..., description="Current interface state")
    interface_type: InterfaceType = Field(..., description="Type of interface")
    mac_address: Optional[str] = Field(None, description="MAC address")
    ip_address: Optional[IPv4Interface] = Field(
        None, description="IP address with netmask"
    )
    gateway: Optional[IPv4Address] = Field(None, description="Gateway IP address")
    table_id: Optional[int] = Field(None, description="Routing table ID")
    has_dhcp_lease: bool = Field(
        False, description="Whether interface has active DHCP lease"
    )


class Messages:
    """Domain events for network control"""

    class InterfaceUp(BaseModel):
        interface: InterfaceInfo

    class InterfaceDown(BaseModel):
        interface: InterfaceInfo

    class InterfaceAddressAssigned(BaseModel):
        interface: InterfaceInfo

    class InterfaceAddressRemoved(BaseModel):
        interface: InterfaceInfo

    class RouteConfigured(BaseModel):
        interface: InterfaceInfo

    class RouteRemoved(BaseModel):
        interface: InterfaceInfo

    class DHCPLeaseAcquired(BaseModel):
        interface: InterfaceInfo

    class DHCPLeaseReleased(BaseModel):
        interface: InterfaceInfo

    class ConnectivityLost(BaseModel):
        interface: InterfaceInfo

    class NetworkControlError(BaseModel):
        model_config = {"arbitrary_types_allowed": True}

        interface_name: str
        error_message: str
        exception: Optional[Exception] = None

        def model_dump(self, **kwargs):
            """Custom serialization that handles Exception objects"""
            data = super().model_dump(**kwargs)
            if self.exception:
                data["exception"] = {
                    "type": type(self.exception).__name__,
                    "message": str(self.exception),
                    "args": self.exception.args,
                }
            return data


class Commands:
    """Commands for network control"""

    class ConfigureInterface(BaseModel):
        interface_name: str
        force_dhcp: bool = Field(False, description="Force DHCP refresh")

    class RemoveInterface(BaseModel):
        interface_name: str

    class FlushRoutes(BaseModel):
        table_id: int

    class GetInterfaceStatus(BaseModel):
        interface_name: Optional[str] = Field(
            None, description="Specific interface or all if None"
        )

    class AddHostRoute(BaseModel):
        host: str = Field(..., description="FQDN or IP address")
        interface_name: str = Field(..., description="Interface to route through")
        table_id: Optional[int] = Field(default=None)

    class RemoveHostRoute(BaseModel):
        host: str = Field(..., description="FQDN or IP address")
        interface_name: str = Field(..., description="Interface to remove route from")
        table_id: Optional[int] = Field(default=None)


class HostRouteResult(BaseModel):
    """Result of host route operations"""

    success: bool = Field(..., description="Whether the operation succeeded")
    host: str = Field(..., description="The host that was processed")
    resolved_ip: Optional[str] = Field(
        None, description="Resolved IP address (for FQDN hosts)"
    )
    interface_name: str = Field(..., description="Interface used for the operation")
    error_message: Optional[str] = Field(
        None, description="Error message if operation failed"
    )
