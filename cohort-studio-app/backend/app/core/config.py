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

    # --------------------------------------------------------------- data
    # The tables to read (config/mapping.yaml by default). Point MAPPING_PATH
    # at another file when the tables live under another catalog or schema.
    mapping_path: Path = DEFAULT_MAPPING
    # The SQL warehouse to read through: the app resource "sql-warehouse".
    databricks_warehouse_id: str | None = None
    db_statement_timeout_ms: int = Field(120_000, ge=1000)

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

    @field_validator("databricks_warehouse_id", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("mcp_token", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
