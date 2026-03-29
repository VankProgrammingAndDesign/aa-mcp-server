from pydantic import BaseModel


class Bot(BaseModel):
    id: str
    name: str
    folder_path: str = ""
    type: str = ""
    last_modified: str | None = None


class Device(BaseModel):
    id: str
    hostname: str
    status: str
    username: str = ""


class DeployResponse(BaseModel):
    deployment_id: str
    status: str
    bot_name: str = ""
    device_hostname: str = ""
    queued_at: str = ""
