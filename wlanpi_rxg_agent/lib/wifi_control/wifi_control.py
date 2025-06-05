from abc import ABC, abstractmethod


class WifiControl(ABC):

    def __init__(self):
        self.core_client
