from pydantic import BaseModel


class ActivityRecord(BaseModel):
    activity_id: str
    bot_name: str
    device_hostname: str = ""
    started_at: str = ""
    ended_at: str | None = None
    duration_seconds: int | None = None
    status: str
    error_message: str | None = None
