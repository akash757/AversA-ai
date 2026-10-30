import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    INTERNAL_SERVICE_TOKEN: str
    GOOGLE_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "the-thunder-agent"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# Sync LangChain / LangSmith environment variables if tracing is enabled
if settings.LANGSMITH_TRACING:
    os.environ["LANGSMITH_TRACING"] = "true"
    if settings.LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    if settings.LANGCHAIN_PROJECT:
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
