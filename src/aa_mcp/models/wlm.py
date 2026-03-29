from pydantic import BaseModel


class Queue(BaseModel):
    id: str
    name: str
    status: str = ""
    pending_count: int = 0
    in_progress_count: int = 0
    completed_count: int = 0
    failed_count: int = 0


class WorkItem(BaseModel):
    id: str
    status: str
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
