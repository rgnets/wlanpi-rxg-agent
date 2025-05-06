import asyncio
import logging
from typing import Callable


# Inspired by https://www.joeltok.com/posts/2021-03-building-an-event-bus-in-python/

class EventBus():
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        self.listeners = {}

    def add_listener(self, event_name, listener:Callable):
        self.logger.debug(f"New listener on event {event_name}: {listener.__name__}")
        if not self.listeners.get(event_name, None):
            self.listeners[event_name] = {listener}
        else:
            self.listeners[event_name].add(listener)

    def remove_listener(self, event_name, listener:Callable):
        self.logger.debug(f"Removing listener from event {event_name}: {listener.__name__}")
        self.listeners[event_name].remove(listener)
        if len(self.listeners[event_name]) == 0:
            del self.listeners[event_name]

    def emit(self, event_name, event=None):
        self.logger.debug(f"Emitting on event {event_name}: {event}")
        listeners = self.listeners.get(event_name, [])
        for listener in listeners:
            asyncio.create_task(listener(event))
