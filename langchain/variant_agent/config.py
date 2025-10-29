from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(
        default=None, alias="OPENAI_BASE_URL", description="Override the OpenAI base URL."
    )
    openai_model: str = Field(default="gpt-5-mini", alias="OPENAI_MODEL")
    openai_temperature: Optional[float] = Field(
        default=None,
        alias="OPENAI_TEMPERATURE",
        description="Optional temperature override; leave unset to use model default.",
    )
    openai_stream: bool = Field(
        default=False,
        alias="OPENAI_STREAM",
        description="Set true to enable streaming responses (disabled by default).",
    )
    auth_bearer: str = Field(default="9786534210", alias="AUTH_BEARER")
    port: int = Field(default=28899, alias="PORT")
    log_intermediate: bool = Field(default=False, alias="LOG_INTERMEDIATE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()  # type: ignore[arg-type]
