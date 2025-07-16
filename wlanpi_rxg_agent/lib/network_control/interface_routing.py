from pyroute2 import IPRoute
import ipaddress


class InterfaceRouterManager:
    def __init__(self):
        self.ip = IPRoute()

    def get_index(self, ifname):
        result = self.ip.link_lookup(ifname=ifname)
        if not result:
            raise ValueError(f"Interface '{ifname}' not found")
        return result[0]

    def add_route_and_rule(self, ifname, src_ip, gateway, table_id, priority=None):
        idx = self.get_index(ifname)
        priority = priority or table_id  # default priority to match table

        # Add default route in custom table
        self.ip.route('add',
                      dst='default',
                      gateway=gateway,
                      oif=idx,
                      table=table_id)

        # Add a rule that sends traffic from src_ip via this table
        self.ip.rule('add',
                     src=src_ip,
                     table=table_id,
                     priority=priority)

    def remove_route_and_rule(self, ifname, src_ip, gateway, table_id, priority=None):
        idx = self.get_index(ifname)
        priority = priority or table_id

        try:
            self.ip.route('del',
                          dst='default',
                          gateway=gateway,
                          oif=idx,
                          table=table_id)
        except Exception as e:
            print(f"Warning: route delete failed: {e}")

        try:
            self.ip.rule('del',
                         src=src_ip,
                         table=table_id,
                         priority=priority)
        except Exception as e:
            print(f"Warning: rule delete failed: {e}")

    def list_rules(self):
        return self.ip.get_rules()

    def flush_routes(self, table_id):
        routes = self.ip.get_routes(table=table_id)
        for route in routes:
            self.ip.route('del', **route)

    def close(self):
        self.ip.close()

