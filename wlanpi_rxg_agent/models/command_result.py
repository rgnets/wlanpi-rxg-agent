import json
import re
from json import JSONDecodeError
from re import RegexFlag
from typing import Union, Any
from enum import Enum


class CommandResult:
    """Returned by run_command"""

    def __init__(self, stdout: str, stderr: str, return_code: int):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.success = self.return_code == 0

    def output_from_json(self) -> Union[dict, list, int, float, str, None]:
        try:
            return json.loads(self.stdout)
        except JSONDecodeError:
            return None

    def error_from_json(self) -> Union[dict, list, int, float, str, None]:
        try:
            return json.loads(self.stderr)
        except JSONDecodeError:
            return None

    def grep_stdout_for_string(
        self, string: str, negate: bool = False, split: bool = False
    ) -> Union[str, list[str]]:
        if negate:
            filtered = list(filter(lambda x: string not in x, self.stdout.split("\n")))
        else:
            filtered = list(filter(lambda x: string in x, self.stdout.split("\n")))
        return filtered if split else "\n".join(filtered)

    def grep_stdout_for_pattern(
        self,
        pattern: Union[re.Pattern[str], str],
        flags: Union[int, RegexFlag] = 0,
        negate: bool = False,
        split: bool = False,
    ) -> Union[str, list[str]]:
        if negate:
            filtered = list(
                filter(
                    lambda x: not re.match(pattern, x, flags=flags),
                    self.stdout.split("\n"),
                )
            )
        else:
            filtered = list(
                filter(
                    lambda x: re.match(pattern, x, flags=flags), self.stdout.split("\n")
                )
            )
        return filtered if split else "\n".join(filtered)

    def to_json(self) -> str:
        """Serialize the object to JSON."""
        return json.dumps(self, default=self._json_encoder, indent=2)

    @staticmethod
    def _json_encoder(obj: Any) -> Any:
        """Custom JSON encoder to handle non-serializable types."""
        if isinstance(obj, (CommandResult,)):  # Include other custom types if needed
            dict_form = obj.__dict__
            dict_form["output_from_json"] = obj.output_from_json
            dict_form["error_from_json"] = obj.error_from_json
            return dict_form
        elif isinstance(obj, (re.Pattern, RegexFlag)):
           return str(obj)  # Or a more meaningful representation if available
        elif isinstance(obj, Enum):
            return obj.value
        return json.JSONEncoder().default(obj) # Let the base encoder handle other types
