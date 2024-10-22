import datetime
import json
import subprocess
import time
from typing import Any, Optional

from wlanpi_rxg_agent.models.command_result import CommandResult
from wlanpi_rxg_agent.models.runcommand_error import RunCommandError


def run_command(cmd: list, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with subprocess and returns the output"""
    print("Running command:", cmd)
    cp = subprocess.run(
        cmd,
        encoding="utf-8",
        shell=shell,
        check=False,
        capture_output=True,
    )
    if raise_on_fail and cp.returncode != 0:
        raise RunCommandError(cp.stderr, cp.returncode)
    return CommandResult(cp.stdout, cp.stderr, cp.returncode)


def get_full_class_name(obj: object) -> str:
    """
    Gets the full class name and path of an object for use in errors.
    :param obj: The object to get the name and path of
    :return: The full name and path as a string.
    """
    module = obj.__class__.__module__
    if module is None or module == str.__class__.__module__:
        return obj.__class__.__name__
    return module + "." + obj.__class__.__name__


def get_default_gateways() -> dict[str, str]:
    # Execute 'ip route show' command which lists all network routes
    cmd = "ip route show"
    output = run_command(cmd.split(" ")).output.split("\n")

    gateways: dict[str, str] = {}
    for line in output:
        if "default via" in line:  # This is the default gateway line
            res = line.split("via ")[1].split(" dev ")
            gateways[res[1].strip()] = res[0].strip()
    return gateways


def trace_route(target: str) -> dict[str, Any]:
    # Execute 'ip route show' command which lists all network routes
    output = run_command(["jc", "traceroute", target]).output_from_json()
    return output


def get_model_info() -> dict[str, str]:
    model_info = run_command(["wlanpi-model"]).output.split("\n")
    split_model_info = [a.split(":", 1) for a in model_info if a.strip() != ""]
    model_dict = {}
    for a, b in split_model_info:
        model_dict[a.strip()] = b.strip()
    return model_dict


def get_uptime() -> dict[str, str]:
    cmd = "jc uptime"
    return run_command(cmd.split(" ")).output_from_json()


def get_hostname() -> str:
    cmd = "uptime"
    return run_command(cmd.split(" ")).output


def get_interface_ip_addr(interface: Optional[str] = None) -> dict[str, Any]:
    cmd: list[str] = "ip -j addr show".split(" ")
    if interface is not None and interface.strip() != "":
        cmd.append(interface.strip())
    return run_command(cmd).output_from_json()


def get_current_unix_timestamp():
    ms = datetime.datetime.now()
    return time.mktime(ms.timetuple()) * 1000


def get_eth0_mac() -> str:
    eth0_res = subprocess.run(
        "jc ifconfig eth0", capture_output=True, text=True, shell=True
    )
    eth0_data = json.loads(eth0_res.stdout)[0]
    return eth0_data["mac_addr"]


if __name__ == "__main__":
    print(get_interface_ip_addr())
