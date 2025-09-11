import os
from pathlib import Path

import toml

from wlanpi_rxg_agent.lib.configuration.config_file import ConfigFile


def test_atomic_save_and_load(tmp_path):
    cfg_path = tmp_path / "testconfig.toml"
    cf = ConfigFile(str(cfg_path), defaults={"Section": {"key": "value"}})
    cf.create_defaults()
    cf.data["Section"]["key"] = "newval"
    cf.save()

    # Ensure file exists, no leftover temp file, and content matches
    assert cfg_path.exists()
    assert not (tmp_path / "testconfig.toml.tmp").exists()
    loaded = toml.load(cfg_path)
    assert loaded["Section"]["key"] == "newval"


def test_agent_config_validation_fallback(tmp_path, monkeypatch):
    # Redirect agent config dir to a temp dir
    from wlanpi_rxg_agent.lib.configuration import agent_config_file as acf_mod

    temp_dir = tmp_path / "agent"
    temp_dir.mkdir()
    monkeypatch.setattr(acf_mod, "AGENT_CONFIG_DIR", str(temp_dir))

    # Write invalid toml (numeric where string expected)
    cfg_file = temp_dir / "config.toml"
    cfg_file.write_text(
        """
[General]
override_rxg = 123
fallback_rxg = 456
"""
    )

    acf = acf_mod.AgentConfigFile()
    acf.load_or_create_defaults(allow_empty=False)

    # Should fall back to defaults (empty strings)
    assert acf.data["General"]["override_rxg"] == ""
    assert acf.data["General"]["fallback_rxg"] == ""


def test_bridge_config_validation_fallback(tmp_path, monkeypatch):
    # Redirect bridge config dir to a temp dir
    from wlanpi_rxg_agent.lib.configuration import bridge_config_file as bcf_mod

    temp_dir = tmp_path / "bridge"
    temp_dir.mkdir()
    monkeypatch.setattr(bcf_mod, "BRIDGE_CONFIG_DIR", str(temp_dir))

    # Write invalid toml (port as string)
    cfg_file = temp_dir / "config.toml"
    cfg_file.write_text(
        """
[MQTT]
server = "192.0.2.1"
port = "notanint"

[MQTT_TLS]
use_tls = true
cert_reqs = 2
"""
    )

    bcf = bcf_mod.BridgeConfigFile()
    bcf.load_or_create_defaults(allow_empty=False)

    # Should fall back to defaults (port 1883)
    assert bcf.data["MQTT"]["port"] == 1883
