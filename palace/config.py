"""Palace Memory Service configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://palace:palace@localhost/palace",
        validation_alias="PALACE_DATABASE_URL",
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "palace_memories"
    embedding_provider: str = "huggingface"
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    hf_token: str | None = None
    openai_api_key: str | None = None
    llm_provider: str = "openrouter"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-4o-mini"
    log_level: str = "INFO"

    # Auth (slice 1)
    auth_disabled: bool = Field(default=False, validation_alias="PALACE_AUTH_DISABLED")
    bootstrap_admin_key: str | None = Field(
        default=None, validation_alias="PALACE_BOOTSTRAP_ADMIN_KEY",
    )

    # Multi-tenancy (slice 2)
    default_tenant_id: str = Field(
        default="default", validation_alias="PALACE_DEFAULT_TENANT_ID",
    )

    # Graph (slice 3) — FalkorDB. Unset = no-op.
    falkordb_url: str | None = Field(
        default=None, validation_alias="PALACE_FALKORDB_URL",
    )

    # Cache (slice 4) — Redis. Unset = no-op.
    redis_url: str | None = Field(
        default=None, validation_alias="PALACE_REDIS_URL",
    )
    cache_disabled: bool = Field(
        default=False, validation_alias="PALACE_CACHE_DISABLED",
    )
    cache_ttl_search_seconds: int = Field(default=60, validation_alias="PALACE_CACHE_TTL_SEARCH")
    cache_ttl_get_seconds: int = Field(default=300, validation_alias="PALACE_CACHE_TTL_GET")

    # gRPC (slice 5) — port unset = HTTP-only.
    grpc_port: int | None = Field(default=None, validation_alias="PALACE_GRPC_PORT")
    grpc_host: str = Field(default="0.0.0.0", validation_alias="PALACE_GRPC_HOST")

    # Observability (phase 4 slice 2)
    otlp_endpoint: str | None = Field(
        default=None, validation_alias="PALACE_OTLP_ENDPOINT",
    )
    otlp_service_name: str = Field(
        default="palace-memory", validation_alias="PALACE_OTLP_SERVICE_NAME",
    )
    log_format: str = Field(
        default="pretty", validation_alias="PALACE_LOG_FORMAT",
    )  # "pretty" or "json"


settings = Settings()
