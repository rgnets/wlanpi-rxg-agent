import logging
import time
from typing import Any, Optional

import requests
from requests.compat import json as complexjson, chardet
from aiohttp import ClientSession, ClientResponse
from pydantic import BaseModel

from requests import JSONDecodeError
from requests.models import guess_json_utf
from requests.structures import CaseInsensitiveDict


class FlatResponse:
    """ Yes, I ripped some guts out of the Requests library for this. Use this to emulate as much of a Requests response as needed."""

    def __init__(self, headers: CaseInsensitiveDict[str], url: str, status_code: int, content: bytes,
                 encoding: Optional[str] = None):
        self.headers = headers
        self.url = url
        self.status_code = status_code
        self.content = content
        self.encoding = encoding

    @property
    def apparent_encoding(self):
        """The apparent encoding, provided by the charset_normalizer or chardet libraries."""
        if chardet is not None:
            return chardet.detect(self.content)["encoding"]
        else:
            # If no character detection library is available, we'll fall back
            # to a standard Python utf-8 str.
            return "utf-8"

    @property
    def text(self):
        """Content of the response, in unicode.

        If Response.encoding is None, encoding will be guessed using
        ``charset_normalizer`` or ``chardet``.

        The encoding of the response content is determined based solely on HTTP
        headers, following RFC 2616 to the letter. If you can take advantage of
        non-HTTP knowledge to make a better guess at the encoding, you should
        set ``r.encoding`` appropriately before accessing this property.
        """

        # Try charset from content-type
        content = None
        encoding = self.encoding

        if not self.content:
            return ""

        # Fallback to auto-detected encoding.
        if self.encoding is None:
            encoding = self.apparent_encoding

        # Decode unicode from given encoding.
        try:
            content = str(self.content, encoding, errors="replace")
        except (LookupError, TypeError):
            # A LookupError is raised if the encoding was not found which could
            # indicate a misspelling or similar mistake.
            #
            # A TypeError can be raised if encoding is None
            #
            # So we try blindly encoding.
            content = str(self.content, errors="replace")

        return content

    def json(self, **kwargs):
        r"""Returns the json-encoded content of a response, if any.

        :param \*\*kwargs: Optional arguments that ``json.loads`` takes.
        :raises requests.exceptions.JSONDecodeError: If the response body does not
            contain valid json.
        """

        if not self.encoding and self.content and len(self.content) > 3:
            # No encoding set. JSON RFC 4627 section 3 states we should expect
            # UTF-8, -16 or -32. Detect which one to use; If the detection or
            # decoding fails, fall back to `self.text` (using charset_normalizer to make
            # a best guess).
            encoding = guess_json_utf(self.content)
            if encoding is not None:
                try:
                    return complexjson.loads(self.content.decode(encoding), **kwargs)
                except UnicodeDecodeError:
                    # Wrong UTF codec detected; usually because it's not UTF-8
                    # but some other 8-bit codec.  This is an RFC violation,
                    # and the server didn't bother to tell us what codec *was*
                    # used.
                    pass
                except JSONDecodeError as e:
                    raise requests.JSONDecodeError(e.msg, e.doc, e.pos)

        try:
            return complexjson.loads(self.text, **kwargs)
        except JSONDecodeError as e:
            # Catch JSON-related errors and raise as requests.JSONDecodeError
            # This aliases json.JSONDecodeError and simplejson.JSONDecodeError
            raise requests.JSONDecodeError(e.msg, e.doc, e.pos)


class CoreClient:
    def __init__(
            self,
            base_url="http://127.0.0.1:31415",
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing CoreClient against {base_url}")
        self.base_url = base_url
        self.api_url = f"{base_url}/api/v1"
        self.openapi_def_path = f"{self.api_url}/openapi.json"

        self.base_headers = {
            "accept": "application/json",
            # "content-type": "application/x-www-form-urlencoded",
        }
        self.logger.info("CoreClient initialized")

    def get_openapi_definition(self) -> dict:
        self.logger.debug(f"Fetching OpenAPI definition from {self.openapi_def_path}")

        while True:
            try:
                return requests.get(
                    url=self.openapi_def_path, headers=self.base_headers
                ).json()
            except JSONDecodeError:
                self.logger.warning(
                    f"Failed to fetch OpenAPI definition from {self.openapi_def_path}"
                    ", waiting 5 seconds."
                )
                time.sleep(5)

    def execute_request(
            self,
            method: str,
            path: str,
            data: Optional[Any] = None,
            params: Optional[Any] = None,
    ) -> requests.Response:
        self.logger.debug(
            f"Executing {method.upper()} on path {path} with data: {str(data)}"
        )
        response = requests.request(
            method=method,
            params=params,
            url=f"{self.base_url}/{path}",
            json=data,
            headers=self.base_headers,
        )
        return response

    async def execute_async_request(
            self,
            method: str,
            path: str,
            data: Optional[Any] = None,
            params: Optional[Any] = None,
    ) -> FlatResponse:
        self.logger.debug(
            f"Executing {method.upper()} asynchonously on path {path} with data: {str(data)}"
        )

        async with ClientSession() as session:
            async with session.request(
                    method=method,
                    params=params,
                    url=f"{self.base_url}/{path}",
                    json=data,
                    headers=self.base_headers,
            ) as response:
                self.logger.debug(
                    f"Returning response for {method.upper()} on path {path} with data: {str(data)}"
                )
                # Returning a flat response here to make our lives easier. Do NOT return the raw ClientResponse object!
                # The async methods will not work outside the context providers above!
                # If you find yourself needing more data or in a different form, modify the
                # FlatResponse class to accommodate.
                return FlatResponse(
                    headers=response.headers,
                    url=str(response.url),
                    status_code=response.status,
                    content=await response.content.read(),
                    encoding=response.get_encoding()
                )

    def get_current_path_data(self, path):
        self.logger.debug(f"Getting current path data for {path}")
        response = self.execute_request("get", path)
        if response.status_code != 200:
            self.logger.error("Unable to get vlan data")
            return "ERROR"
        return response.json()

    def create_on_path(self, path, data):
        """Probably not actually going to use this."""
        self.logger.info(f"Creating data on path {path}")
        target_url = f"{self.api_url}/{path}/create"
        self.logger.debug(f"Creating with URL {target_url} and data {data}")
        response = self.execute_request(
            "post",
            path,
            data=data,
        )
        if response.status_code != 200:
            self.logger.error("Unable to successfully relay data")
            self.logger.error(f"Code: {response.status_code} Reason: {response.reason}")
            self.logger.error(response.raw)
            return "ERROR"
        return response.json()
