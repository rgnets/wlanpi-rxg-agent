import asyncio
from pyroute2 import IPRoute, NetlinkError, AsyncIPRoute
from pyroute2.netlink.rtnl import RTM_NEWADDR, RTM_DELADDR


class AsyncNetlinkMonitor:
    def __init__(self, loop=None):
        self.ipr = AsyncIPRoute()
        self.loop = loop or asyncio.get_event_loop()

    def monitor(self, callback):
        # Add IPRoute fd to asyncio loop
        pass
        # self.ipr.
        # self.loop.add_reader(fd, self._on_event, callback)


    def _on_event(self, callback):
        try:
            for msg in self.ipr.get():
                if msg['event'] in (RTM_NEWADDR, RTM_DELADDR):
                    callback(msg)
        except NetlinkError as e:
            print(f"[Netlink error] {e}")
