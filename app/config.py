from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    # Google Gemini API Settings
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.8-flash"

    # Groq Cross-Provider Fallback Settings
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 4000

    # Scraper & Extractor Settings
    REQUEST_TIMEOUT_SECONDS: int = 15
    MAX_CONTENT_CHARS: int = 12000

    # In-memory TTL Cache Settings
    CACHE_TTL_SECONDS: int = 3600
    CACHE_MAXSIZE: int = 1000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
