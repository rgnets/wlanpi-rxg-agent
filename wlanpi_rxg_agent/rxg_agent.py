from pprint import pp

import requests

from wlanpi_rxg_agent.utils import get_default_gateways


def find_rxg():
    return get_default_gateways()



def main():

    pp(get_default_gateways())
    return None