import pytest
from wlanpi_rxg_agent.lib.rxg_supplicant.supplicant import RxgSupplicant
from requests.exceptions import ConnectTimeout, ConnectionError, ReadTimeout

@pytest.fixture
def mocked_test_check_device_unknown_device(mocker):
    # Set up the mocked ApiClient instance to return a successful response
    MockedAPIClient = mocker.patch('wlanpi_rxg_agent.lib.rxg_supplicant.supplicant.ApiClient')
    mocked_response = mocker.Mock()

    mocked_response.status_code = 200
    mocked_response.json.return_value = {
        "message": "Unknown device",
        "status": "unregistered"
    }

    mocked_api = MockedAPIClient.return_value
    mocked_api.check_device.return_value = mocked_response

@pytest.fixture
def mocked_test_check_device_no_response(mocker):
    # Set up the mocked ApiClient instance to return a failing response
    MockedAPIClient = mocker.patch('wlanpi_rxg_agent.lib.rxg_supplicant.supplicant.ApiClient')
    mocked_api = MockedAPIClient.return_value
    mocked_response = mocker.Mock()
    mocked_response.status_code = 404
    mocked_api.check_device.side_effect = ConnectTimeout("No Response")


def test_test_address_for_rxg_passing(mocked_test_check_device_unknown_device):

    # Instantiate the RxgSupplicant class
    instance = RxgSupplicant()

    # Call test_address_for_rxg with a fake IP
    result = instance.test_address_for_rxg("192.0.2.5")

    # Assert that it returned True
    assert result == True


def test_test_address_for_rxg_failing(mocked_test_check_device_no_response):

    # Instantiate the RxgSupplicant class
    instance = RxgSupplicant()

    # Call test_address_for_rxg with a fake IP
    result = instance.test_address_for_rxg("192.0.2.5")

    # Assert that it returned False
    assert result == False
