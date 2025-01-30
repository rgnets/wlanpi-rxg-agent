from enum import Enum
import typing as t


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
    class Certified(t.NamedTuple):
        pass
    class CertificationFailed(t.NamedTuple):
        pass
    class Monitoring(t.NamedTuple):
        pass
    class NewServer(t.NamedTuple):
        pass
    class Error(t.NamedTuple):
        error: Exception
