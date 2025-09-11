from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AgentGeneral(BaseModel):
    override_rxg: Optional[str] = Field(default="")
    fallback_rxg: Optional[str] = Field(default="")

    @field_validator("override_rxg", "fallback_rxg", mode="before")
    def empty_to_str(cls, v):  # noqa: N805
        if v is None:
            return ""
        return v


class AgentConfig(BaseModel):
    General: AgentGeneral = Field(default_factory=AgentGeneral)


class BridgeMQTT(BaseModel):
    server: str = Field(default="127.0.0.1")
    port: int = Field(default=1883)


class BridgeMQTTTLS(BaseModel):
    use_tls: bool = Field(default=False)
    ca_certs: Optional[str] = Field(default=None)
    certfile: Optional[str] = Field(default=None)
    keyfile: Optional[str] = Field(default=None)
    cert_reqs: int = Field(default=2)


class BridgeConfig(BaseModel):
    MQTT: BridgeMQTT = Field(default_factory=BridgeMQTT)
    MQTT_TLS: BridgeMQTTTLS = Field(default_factory=BridgeMQTTTLS)
