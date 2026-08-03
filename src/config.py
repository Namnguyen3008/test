from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "VMEC-01"
    app_env: Literal["development", "review", "production", "test"] = "development"
    app_data_mode: Literal["development", "review", "production"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "127.0.0.1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM
    gemini_api_key: SecretStr = SecretStr("")
    gemini_generative_model_1: str = "gemini-3.1-flash-lite"
    gemini_generative_model_2: str = "gemini-3.5-flash-lite"
    gemini_generative_models: str = "gemini-3.1-flash-lite,gemini-3.5-flash-lite"
    gemini_generative_routing_mode: str = "redis_round_robin"
    gemini_round_robin_redis_key: str = "vmec:gemini:generative:round_robin:v1"
    gemini_call_timeout_seconds: float = Field(default=30, gt=0, le=120)
    gemini_max_attempts_per_model: int = Field(default=2, ge=1, le=5)
    gemini_embedding_primary_model: str = "gemini-embedding-2"
    gemini_embedding_text_fallback_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 768
    redis_url: str = "redis://localhost:6379/0"

    # Database
    database_url: str = "sqlite:///./data/app.db"

    @model_validator(mode="after")
    def validate_exact_ai_policy(self) -> "Settings":
        expected = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite")
        configured = tuple(part.strip() for part in self.gemini_generative_models.split(","))
        if (
            (self.gemini_generative_model_1, self.gemini_generative_model_2) != expected
            or configured != expected
            or self.gemini_generative_routing_mode != "redis_round_robin"
        ):
            raise ValueError("Forbidden Gemini generative model configuration")
        if (
            self.gemini_embedding_primary_model != "gemini-embedding-2"
            or self.gemini_embedding_text_fallback_model != "gemini-embedding-001"
            or self.gemini_embedding_dimensions != 768
        ):
            raise ValueError("Forbidden Gemini embedding configuration")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
