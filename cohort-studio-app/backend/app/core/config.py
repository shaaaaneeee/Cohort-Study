"""Settings, all from environment variables (or a .env file in development).

Every variable is documented in backend/.env.example. Nothing here has a
secret default.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_MAPPING = BACKEND_DIR / "config" / "mapping.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ------------------------------------------------------------- server
    app_env: Literal["development", "test", "production"] = "production"
    host: str = "0.0.0.0"  # noqa: S104 - inside a container the app must listen on all interfaces
    # A Databricks App must listen on the port the platform gives it.
    port: int = Field(
        8000, ge=1, le=65535, validation_alias=AliasChoices("databricks_app_port", "port")
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    # Origins allowed to call /mcp from a browser, comma separated: the
    # workspace URL, for Genie Code. Empty means none.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Optional. When set, every /mcp request must send
    # "Authorization: Bearer <MCP_TOKEN>". Leave it unset in a Databricks App:
    # Databricks signs in every caller before a request reaches the app.
    mcp_token: SecretStr | None = None

    # ----------------------------------------------------------- database
    # The mapping decides the database: config/mapping.databricks.yaml reads a
    # Databricks SQL warehouse (DATABRICKS_WAREHOUSE_ID), config/mapping.yaml
    # PostgreSQL, for local runs and tests (DATABASE_URL or the DB_* settings).
    database_url: SecretStr | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "cohort"
    db_user: str = "cohort_app"
    db_password: SecretStr | None = None
    db_sslmode: str | None = None
    db_pool_size: int = Field(5, ge=1)
    db_max_overflow: int = Field(5, ge=0)
    db_statement_timeout_ms: int = Field(120_000, ge=1000)
    mapping_path: Path = DEFAULT_MAPPING
    # The Databricks SQL warehouse to read from, when the mapping's backend
    # dialect is "databricks" (config/mapping.databricks.yaml).
    databricks_warehouse_id: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("mapping_path", mode="before")
    @classmethod
    def _blank_mapping_is_default(cls, value: object) -> object:
        return DEFAULT_MAPPING if value in ("", None) else value

    @field_validator(
        "db_sslmode",
        "databricks_warehouse_id",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("mcp_token", "database_url", "db_password", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
