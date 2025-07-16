import json
import logging
import pprint

import asyncio

import pyroute2

from pprint import pp, pformat

from lib.network_control.dhcp_lease_parser import DHCPLeaseParser
from lib.network_control.interface_routing import InterfaceRouterManager
from lib.network_control.netlink_monitor import AsyncNetlinkMonitor
from rxg_agent import CustomFormatter

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(CustomFormatter())


logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.DEBUG, handlers=[ch])
logging.getLogger("pyroute2.netlink.core").setLevel(logging.WARNING)
logging.getLogger("pyroute2.ndb").setLevel(logging.WARNING)

if __name__ == "__main__":



    log = logging.getLogger(__name__)

    #
    # router = InterfaceRouterManager()
    # pprint.pp(router.list_rules())
    # pprint.pp(router.get_index("wlan1"))
    #
    # dhcp = DHCPLeaseParser("wlan1")
    # pprint.pp(dhcp.latest_lease())


    async def silly_loop():
        while True:
            print("Goof Loop")
            await asyncio.sleep(10)


    async def netlink_watcher():
        async with pyroute2.AsyncIPRSocket(all_ns=True) as aiprs:
            await aiprs.bind()
            while True:
                async for msg in await aiprs.get():
                    log.info(f" EVENT: {pprint.pformat(msg)}")


    async def main():
        # sip_test = SipTestBaresip(gateway="192.168.7.15", user="pi2", password="pitest", debug=True)
        # await sip_test.execute(callee="1101", post_connect="1234", call_timeout=2)
        log.info("Starting")

        tasks: list[asyncio.Task] = []

        tasks.append(asyncio.create_task(silly_loop()))
        tasks.append(asyncio.create_task(netlink_watcher()))

        ipr = pyroute2.AsyncIPRoute(all_ns=True)

        # async for link in await ipr.link("dump"):
        #     log.info(pprint.pformat(link.get("ifname")))

        # routes = await ipr.get_routes(await ipr.link_lookup(ifname="wlan1"))

        # log.info(json.dumps(routes, indent=4))
        #
        # async for route in routes:
        #     log.info(pprint.pformat(route.get('RTA_TABLE')))

        # log.info(pformat(list(n async for n in neighbors )))


        # monitor = AsyncNetlinkMonitor()
        # monitor.monitor(lambda x: pprint.pp(x))
        #
        # with pyroute2.NDB() as ndb:
        #     ifs = ndb.routes.summary()
        #     log.info(pformat(ifs))
        #

        async with pyroute2.AsyncIPRoute(all_ns=True) as aipr:
            routes = await aipr.get_routes()
            flat_routes = []
            async for route in routes:
                # print(route)
                flat_routes.append(route)

            print("done")




        # Test setting up route

        with pyroute2.NDB() as ndb:



            log.warn("Sleeping 10 seconds while you check route tables!")
            await asyncio.sleep(10)

            ndb.routes.create(
                dst='192.168.6.0/24',
                gateway='192.168.6.1',
                interface='wlan1',
                table=11
            ).commit()
            ndb.routes.create(
                dst='default',
                gateway='192.168.6.1',
                interface='wlan1',
                priority=200,
                table=11
            ).commit()



        await asyncio.gather(*tasks)





    asyncio.get_event_loop().run_until_complete(main())




  # wlanpi@wlanpi-c8b:~
  #   default via 192.168.6.1 dev wlan1
  #   192.168.6.0/24 dev wlan1 proto kernel scope link src 192.168.6.47


