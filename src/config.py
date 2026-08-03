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
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    otel_service_name: str = "vmec-api"
    otel_exporter_otlp_traces_endpoint: str = ""

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
    retrieval_runtime_mode: Literal["auto", "postgres", "lexical"] = "auto"
    retrieval_statement_timeout_ms: int = Field(default=1500, ge=100, le=30_000)
    retrieval_embedding_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    retrieval_candidate_limit: int = Field(default=50, ge=10, le=200)
    vmec_persistent_pgvector_verified: bool = False
    vmec_allow_full_embedding_backfill: bool = False

    # Authentication
    session_redis_url: str = "redis://localhost:6379/1"
    session_cookie_name: str = "vmec_session"
    session_ttl_seconds: int = Field(default=3600, ge=300, le=2_592_000)
    csrf_secret: SecretStr = SecretStr("development-only-csrf-secret-change-me")

    # Emergency runtime corpus
    emergency_catalog_path: str = "data/staging/vmec_catalog.sqlite3"
    emergency_release_id: str = ""
    approved_corpus_manifest_path: str = "data/source/APPROVED_CORPUS_MANIFEST.json"

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
        if self.app_env == "production" and self.csrf_secret.get_secret_value() == (
            "development-only-csrf-secret-change-me"
        ):
            raise ValueError("Production requires an external CSRF secret")
        if len(self.csrf_secret.get_secret_value()) < 32:
            raise ValueError("CSRF secret must contain at least 32 characters")
        if self.app_env == "production" and not self.database_url.startswith(("postgresql://", "postgresql+")):
            raise ValueError("Production requires PostgreSQL persistence")
        if self.app_env == "production" and not self.session_redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("Production requires Redis-backed sessions")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
