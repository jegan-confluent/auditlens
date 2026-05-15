from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./data/auditlens.db", alias="DATABASE_URL")
    forwarder_health_url: str = Field(default="http://localhost:8003/health", alias="FORWARDER_HEALTH_URL")
    event_retention_days: int = Field(default=7, alias="EVENT_RETENTION_DAYS")
    raw_payload_retention_days: int = Field(default=7, alias="RAW_PAYLOAD_RETENTION_DAYS")
    noise_retention_days: int = Field(default=3, alias="NOISE_RETENTION_DAYS")
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS")
    slow_query_ms: int = Field(default=250, alias="SLOW_QUERY_MS")
    api_title: str = "AuditLens Backend API"
    api_version: str = "0.1.0"
    api_auth_enabled: bool = Field(default=True, alias="API_AUTH_ENABLED")
    confluent_api_base_url: str = Field(default="https://api.confluent.cloud", alias="CONFLUENT_API_BASE_URL")
    confluent_cloud_api_key: str = Field(default="", alias="CONFLUENT_CLOUD_API_KEY")
    confluent_cloud_api_secret: str = Field(default="", alias="CONFLUENT_CLOUD_API_SECRET")
    confluent_api_key: str = Field(default="", alias="CONFLUENT_API_KEY")
    confluent_api_secret: str = Field(default="", alias="CONFLUENT_API_SECRET")

    @property
    def database_mode(self) -> Literal["sqlite", "postgres"]:
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        if self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            return "postgres"
        return "sqlite"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
