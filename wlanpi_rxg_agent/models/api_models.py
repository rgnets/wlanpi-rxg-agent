from pydantic import BaseModel


class DevShutdownRequest(BaseModel):
    CONFIRM: int
