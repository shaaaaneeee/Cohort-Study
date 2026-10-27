"""Settings, all from environment variables (or a .env file in development).

Every variable is documented in backend/.env.example and docs/deployment.md.
Nothing here has a secret default: the database password and the LLM key
must come from the environment.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_MAPPING = BACKEND_DIR / "config" / "mapping.yaml"

LLMProvider = Literal["anthropic", "demo", "scripted"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ------------------------------------------------------------- server
    app_env: Literal["development", "test", "production"] = "production"
    host: str = "0.0.0.0"  # noqa: S104 - inside a container the app must listen on all interfaces
    port: int = Field(8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    # Origins allowed to call the API from a browser, comma separated. Empty
    # means none: the frontend's origin must be set explicitly.
    cors_origins: Annotated[list[str], NoDecode] = []
    # Optional shared key. When set, every /api request must send it in the
    # X-API-Key header. See docs/deployment.md for what it does and does not protect.
    api_key: SecretStr | None = None

    # ----------------------------------------------------------- database
    # Either DATABASE_URL, or the separate DB_* settings below.
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

    # ---------------------------------------------------------------- LLM
    # Left unset, the provider is "anthropic" when LLM_API_KEY is set and the
    # scripted "demo" otherwise, so the app runs without a key.
    llm_provider: LLMProvider | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_timeout_seconds: float = Field(120.0, gt=0)
    llm_script: Path | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("llm_provider", "llm_base_url", "db_sslmode", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("llm_api_key", "api_key", "database_url", "db_password", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def resolved_llm_provider(self) -> LLMProvider:
        if self.llm_provider is not None:
            return self.llm_provider
        return "anthropic" if self.llm_api_key is not None else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
