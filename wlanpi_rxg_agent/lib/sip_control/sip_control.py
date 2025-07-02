from abc import ABC, abstractmethod

class SipInstance(ABC):
    pass

class SipControl(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def get_instance(self, gateway:str, user: str, password: str) -> SipInstance:
        pass




