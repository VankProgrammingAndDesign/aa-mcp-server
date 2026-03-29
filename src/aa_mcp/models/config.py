import functools

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    control_room_url: str
    username: str
    api_key: str
    token_refresh_buffer_seconds: int = 60
    http_timeout_seconds: int = 30
    log_level: str = "WARNING"

    model_config = SettingsConfigDict(
        env_prefix="AA_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("control_room_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
