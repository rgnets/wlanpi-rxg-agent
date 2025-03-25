from enum import Enum
import typing as t
from dataclasses import dataclass

from wlanpi_rxg_agent.lib import domain as agent_domain

PREFIX = "RXG_SUPPLICANT_"
class RxgSupplicantEvents(Enum):
    UNASSOCIATED = PREFIX+"UNASSOCIATED"
    UNREGISTERED = PREFIX+"UNREGISTERED"
    REGISTERING = PREFIX+"REGISTERING"
    REGISTERED = PREFIX+"REGISTERED"
    REGISTRATION_FAILED = PREFIX+"REGISTRATION_FAILED"
    CERTIFYING = PREFIX+"CERTIFYING"
    CERTIFICATION_FAILED = PREFIX+"CERTIFICATION_FAILED"
    CERTIFIED = PREFIX+"CERTIFIED"
    MONITORING = PREFIX+"MONITORING"
    NEW_SERVER = PREFIX+"NEW_SERVER"
    ERROR = PREFIX+"ERROR"


class Messages:
    class Unassociated(t.NamedTuple):
        pass
    class Unregistered(t.NamedTuple):
        pass
    class Registering(t.NamedTuple):
        pass
    class Registered(t.NamedTuple):
        pass
    class RegistrationFailed(t.NamedTuple):
        pass
    class Certifying(t.NamedTuple):
        pass

    @dataclass
    class Certified:
        host: str
        port: int
        status: str
        certificate: str
        ca: str
        ca_file: str
        certificate_file: str
        key_file: str
        cert_reqs: int

        def __eq__(self, other):
            if not isinstance(other, self.__class__):
                return NotImplemented
            return all([
                self.host == other.host,
                self.port == other.port,
                self.status == other.status,
                self.certificate == other.certificate,
                self.ca == other.ca,
                self.ca_file == other.ca_file,
                self.certificate_file == other.certificate_file,
                self.key_file == other.key_file,
                self.cert_reqs == other.cert_reqs,
            ])

    class NewCertifiedConnection(Certified):
        pass

    class RestartInternalMqtt(Certified):
        pass

    class CertificationFailed(t.NamedTuple):
        pass
    class Monitoring(t.NamedTuple):
        pass
    class NewServer(t.NamedTuple):
        pass

    class Error(agent_domain.Messages.Error):
        pass