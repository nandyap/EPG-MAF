"""Global settings — infrastructure and environment only."""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # DB
    db_path: str = "test_data/clinical_genetics.duckdb"

    # Shared API config — accepts LLM_API_KEY or OPENAI_API_KEY from .env
    llm_api_key: str = Field(
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY")
    )
    llm_base_url: str = "https://api.core42.ai/v1"

    # Agent behaviour
    max_retries: int = 3
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()