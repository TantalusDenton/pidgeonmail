"""Configuration settings for the style learning service."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    api_key: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    # Database Configuration
    database_url: str = "postgresql://styleuser:stylepass@localhost:5432/style_learning"

    # OpenAI Configuration
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Style Learning Configuration
    min_message_length: int = 50
    max_samples_per_user: int = 100
    profile_update_weight: float = 0.3  # Weight for new analysis vs existing profile

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
