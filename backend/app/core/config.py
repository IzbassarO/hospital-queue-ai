from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_name: str = "hospital-queue-ai"
    api_prefix: str = "/api/v1"
    # browser origins allowed by CORS: any port on localhost / 127.0.0.1 (frontend dev servers)
    cors_allow_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    postgres_user: str = "hqai"
    postgres_password: str = "change-me"
    postgres_db: str = "hqai"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
