import json

import requests
from kismet_rest import BaseInterface, KismetLoginException, Utility, KismetRequestException


class KismetCapture(BaseInterface):

    # Have to define our own version of "interact" to handle binary data.
    def interact_binary_stream(self, verb, url_path, **kwargs) -> requests.Response:
        """Wrap all low-level API interaction.

        Args:
            verb (str): ``GET`` or ``POST``.
            url_path (str): Path part of URL.
        Keyword Args:
            payload (dict): Dictionary with POST payload.
            only_status (bool): Only return boolean to represent success or
                failure of operation.
            callback (function): Callback to be used for each JSON object.
            callback_args (list): List of arguments for callback.

        Return:
            Requests.response: raw response API. End user must handle it.
        """
        stream = True
        payload = kwargs["payload"] if "payload" in kwargs else {}
        full_url = Utility.build_full_url(self.host_uri, url_path)
        if verb == "GET":
            self.logger.debug("interact_binary_stream: GET against {} "
                              "stream={}".format(full_url, stream))
            response = self.session.get(full_url, stream=stream)
        elif verb == "POST":
            if payload:
                postdata = json.dumps(payload)
            else:
                postdata = "{}"

            formatted_payload = {"json": postdata}
            self.logger.debug("interact_binary_stream: POST against {} "
                              "with {} stream={}".format(full_url,
                                                         formatted_payload,
                                                         stream))
            response = self.session.post(full_url, data=formatted_payload,
                                         stream=stream)

        else:
            self.logger.error("HTTP verb {} not yet supported!".format(verb))

        # Application error
        if response.status_code == 500:
            msg = "Kismet 500 Error response from {}: {}".format(url_path,
                                                                 response.text)
            self.logger.error(msg)
            raise KismetLoginException(msg, response.status_code)

        # Invalid request
        if response.status_code == 400:
            msg = "Kismet 400 Error response from {}: {}".format(url_path,
                                                                 response.text)
            self.logger.error(msg)
            raise KismetRequestException(msg, response.status_code)

        # login required
        if response.status_code == 401:
            msg = "Login required for {}".format(url_path)
            self.logger.error(msg)
            raise KismetLoginException(msg, response.status_code)

        # Did we succeed?
        if not response.status_code == 200:
            msg = "Request failed {} {}".format(url_path, response.status_code)
            self.logger.error(msg)
            raise KismetRequestException(msg, response.status_code)


        return response



    def capture_all(self)-> requests.Response:
        url = "/pcap/all_packets.pcapng"
        return self.interact_binary_stream("GET", url)

    def capture_by_device(self, key)-> requests.Response:
        url = "devices/pcap/by-key/{}/packets.pcapng".format(key)
        return self.interact_binary_stream("GET", url)


    def capture_by_uuid(self, uuid)-> requests.Response:
        """Capture from source.

        Args:
            uuid (str): UUID of source to capture from.

        Return:
            bool: Success

        """

        url = "/datasource/pcap/by-uuid/{}/packets.pcapng".format(uuid)
        return self.interact_binary_stream("GET", url)