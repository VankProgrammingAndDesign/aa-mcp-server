import functools

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Control Room credentials are optional so the server starts with no
    # configuration — the offline bot-package-analysis and UiPath-migration tools
    # need no Control Room. The Control Room tools raise a clear error at call
    # time (see AuthClient._authenticate) if these are unset.
    control_room_url: str | None = None
    username: str | None = None
    api_key: str | None = None
    token_refresh_buffer_seconds: int = 60
    http_timeout_seconds: int = 30
    log_level: str = "WARNING"
    ssl_verify: bool = True

    model_config = SettingsConfigDict(
        env_prefix="AA_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("control_room_url")
    @classmethod
    def strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
