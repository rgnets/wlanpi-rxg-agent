import pytest
from wlanpi_rxg_agent.lib.rxg_supplicant.supplicant import RxgSupplicant
from requests.exceptions import ConnectTimeout, ConnectionError, ReadTimeout
from test_supplicant_test_address import mocked_test_check_device_unknown_device

@pytest.fixture
def mocked_utils(monkeypatch):
    def get_default_gateways():
        return {
            'eth0': '192.168.30.1',
            'wlan2 metric 200': '192.168.6.1',
            'wlan1 metric 201': '192.168.6.1'
        }

    monkeypatch.setattr('wlanpi_rxg_agent.utils.get_default_gateways', get_default_gateways)

    def trace_route(dest):
        return {
            'hops': [
                {'hop': 0, 'probes': [{'ip': '8.8.8.8'}]},
                {'hop': 1, 'probes': []},
                {'hop': 2, 'probes': [{'ip': '9.9.9.9'}]}
            ]
        }
    monkeypatch.setattr('wlanpi_rxg_agent.utils.trace_route', trace_route)


def test_find_rxg_first_gateway(mocked_utils, mocked_test_check_device_unknown_device):

    # Instantiate the RxgSupplicant class
    instance = RxgSupplicant()

    # Call test_address_for_rxg with a fake IP
    result = instance.find_rxg()

    # Assert that it returned True
    assert result == '192.168.30.1'
