import json
import logging
from ssl import VerifyMode
from typing import Any, Callable, Literal, Optional

import requests
from requests.utils import guess_json_utf

from utils import get_current_unix_timestamp
from requests import JSONDecodeError
from requests.models import guess_json_utf
from requests.structures import CaseInsensitiveDict
from requests.compat import json as complexjson, chardet


class MQTTResponse:
    """
    Standardized MQTT response object that contains details on internal
    failures, REST failures, and the response data. Additionally, it
    tries to parse the response data into JSON but will return the
    original data in case of failure.
    """

    def __init__(
        self,
        data=None,
        errors: Optional[list] = None,
        status: Literal[
            "success", "agent_error", "internal_error", "other_error", "validation_error"
        ] = "success",
        rest_status: Optional[int] = None,
        rest_reason: Optional[str] = None,
        bridge_ident: Optional[Any] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.errors: list = errors or []
        self.status = status
        self.data = data
        self.rest_status = rest_status
        self.rest_reason = rest_reason
        self._bridge_ident = bridge_ident
        self.published_at = get_current_unix_timestamp()
        self.is_hydrated_object = False

        # Try to parse data into json, but don't fret if we can't.
        if type(data) in [str, bytes, bytearray]:
            try:
                self.data = json.loads(data)
                self.is_hydrated_object = True
            except (JSONDecodeError, json.decoder.JSONDecodeError) as e:
                self.logger.debug(
                    f"Tried to decode data as JSON but it was not valid: {str(e)}"
                )
                self.logger.debug(data)
        else:
            # We're going to assume in this case it's some kind of
            # JSON-compatible structure.
            self.is_hydrated_object = True

    def to_json(self) -> str:
        res = json.dumps(
            {
                i: self.__dict__[i]
                for i in self.__dict__
                if (
                    (i not in ["logger", "_bridge_ident"])
                    or (i == "_bridge_ident" and self.__dict__[i])
                )
            },
            default=lambda o: o.__dict__,
            # sort_keys=True,
            # indent=4,
        )
        return res


class TLSConfig:
    def __init__(
        self,
        ca_certs: Optional[str] = None,
        certfile: Optional[str] = None,
        keyfile: Optional[str] = None,
        cert_reqs: Optional[VerifyMode] = None,
        tls_version: Optional[Any] = None,
        ciphers: Optional[str] = None,
        keyfile_password: Optional[Any] = None,
    ):
        self.ca_certs = ca_certs
        self.certfile = certfile
        self.keyfile = keyfile
        self.cert_reqs = cert_reqs
        self.tls_version = tls_version
        self.ciphers = ciphers
        self.keyfile_password = keyfile_password


class BridgeConfig:
    def __init__(
        self,
        mqtt_server: str,
        mqtt_port: int,
        identifier: str,
        tls_config: Optional[TLSConfig] = None,
    ):
        self.mqtt_server = mqtt_server
        self.mqtt_port = mqtt_port
        self.identifier = identifier
        self.tls_config = tls_config


class FlatResponse:
    """ Yes, I ripped some guts out of the Requests library for this. Use this to emulate as much of a Requests response as needed."""

    def __init__(self, headers: CaseInsensitiveDict[str], url: str, status_code: int, content: bytes,
                 encoding: Optional[str] = None, reason: Optional[str]=None):
        self.headers = headers
        self.url = url
        self.status_code = status_code
        self.content = content
        self.encoding = encoding
        self.reason: Optional[str]= reason

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
