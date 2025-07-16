import asyncio
import pprint
import threading
# from messagebus import MessageBus
from interface_routing import InterfaceRouterManager
from netlink_monitor import AsyncNetlinkMonitor
from dhcp_lease_parser import DHCPLeaseParser
from pyroute2.netlink.rtnl import RTM_NEWADDR, RTM_DELADDR
from busses import command_bus, message_bus
#
#
# class DHCPRoutingManager:
#     def __init__(self, iface, table_id):
#         self.iface = iface
#         self.table_id = table_id
#         self.router = InterfaceRouterManager()
#         self.parser = DHCPLeaseParser(iface)
#         self.netmon = AsyncNetlinkMonitor()
#         self.bus = message_bus
#         self.last_ip = None
#         self.last_gateway = None
#         self.register_handlers()
#
#     def register_handlers(self):
#         self.bus.register(self)
#
#     async def start(self):
#         await self.netmon.monitor(self.handle_netlink_event)
#
#     def handle_netlink_event(self, msg):
#         attrs = dict(msg.get('attrs', []))
#         ip = attrs.get('IFA_ADDRESS')
#         if not ip:
#             return
#
#         if msg['event'] == RTM_DELADDR:
#             print(f"[-] IP removed on {self.iface}: {ip}")
#             self.router.remove_route_and_rule(
#                 ifname=self.iface,
#                 src_ip=ip,
#                 gateway=self.last_gateway,
#                 table_id=self.table_id
#             )
#             self.last_ip = None
#             self.last_gateway = None
#             return
#
#         lease = self.parser.latest_lease()
#         if 'fixed_address' not in lease or 'routers' not in lease:
#             print(f"No valid lease found for {self.iface}")
#             return
#
#         src_ip = lease['fixed_address']
#         gateway = lease['routers']
#
#         print(f"[+] IP assigned on {self.iface}: {src_ip} via {gateway}")
#         self.router.add_route_and_rule(
#             ifname=self.iface,
#             src_ip=src_ip,
#             gateway=gateway,
#             table_id=self.table_id
#         )
#         self.last_ip = src_ip
#         self.last_gateway = gateway
#
#     @message_handler("routing.get_status")
#     def get_status(self, message):
#         return {
#             "iface": self.iface,
#             "ip": self.last_ip,
#             "gateway": self.last_gateway,
#             "table_id": self.table_id,
#         }
#
#     @message_handler("routing.flush")
#     def flush_routes(self, message):
#         self.router.flush_routes(self.table_id)
#         return {"flushed": True}
#
#     @message_handler("routing.refresh")
#     def refresh(self, message):
#         lease = self.parser.latest_lease()
#         if 'fixed_address' in lease and 'routers' in lease:
#             self.handle_netlink_event({
#                 "event": RTM_NEWADDR,
#                 "index": self.router.get_index(self.iface),
#                 "attrs": [("IFA_ADDRESS", lease["fixed_address"])]
#             })
#             return {"refreshed": True}
#         return {"refreshed": False}
#
#
# def launch_all_interfaces(iface_table_map):
#     bus = MessageBus()
#     threads = []
#
#     def start_interface(iface, table_id):
#         asyncio.run(DHCPRoutingManager(iface, table_id, message_bus=bus).start())
#
#     for iface, table_id in iface_table_map.items():
#         t = threading.Thread(target=start_interface, args=(iface, table_id), daemon=True)
#         t.start()
#         threads.append(t)
#
#     return bus, threads

