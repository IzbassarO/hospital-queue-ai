from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_name: str = "hospital-queue-ai"
    api_prefix: str = "/api/v1"
    # browser origins allowed by CORS: any port on localhost / 127.0.0.1 (frontend dev servers)
    cors_allow_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    # demo specialist key seeded at container start (`python -m app.cli seed-demo-key`); empty = no demo key
    demo_api_key: str = ""
    # TrueType font with Cyrillic glyphs for PDF export; the first existing path wins
    pdf_font_paths: list[str] = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    pdf_bold_font_paths: list[str] = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    # OpenAPI UI (/docs, /redoc, /openapi.json) — open when enabled; disable in production (docs/security.md)
    docs_enabled: bool = True

    # Assistant proxy (POST /assistant): the provider key lives only here, never in the browser bundle.
    # provider: groq | openrouter | gemini | openai (any OpenAI-compatible chat endpoint); empty key = not configured
    assistant_provider: str = "groq"
    assistant_api_key: str = ""
    assistant_model: str = ""  # empty = the provider's default model (app/services/assistant.py)
    assistant_base_url: str = ""  # empty = the provider's public endpoint

    # level of the application and uvicorn loggers; one JSON line per event on stdout (app/core/logging.py)
    log_level: str = "INFO"
    # X-Forwarded-For is believed only when the TCP peer is one of these networks (the docker bridge by default);
    # every other peer is recorded as it connected, so a forged header cannot rewrite the audit trail
    trusted_proxy_cidrs: list[str] = ["172.16.0.0/12", "127.0.0.0/8", "::1/128"]

    postgres_user: str = "hqai"
    postgres_password: str = "change-me"
    postgres_db: str = "hqai"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    # login role the API uses when the database provides one (db/init.sql): not a superuser and without DDL rights.
    # Empty = connect as postgres_user, which is what the demo stack does (docs/security.md §2).
    app_db_user: str = ""
    app_db_password: str = ""

    # Connection pool of the API process and the per-statement limit every request inherits (docs/security.md §2)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 5
    db_statement_timeout_ms: int = 15000

    def _database_url(self, user: str, password: str) -> str:
        credentials = f"{quote(user, safe='')}:{quote(password, safe='')}"
        return f"postgresql+psycopg://{credentials}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url(self) -> str:
        """Owner role: Alembic migrations, the seed loader and the ML pipelines."""
        return self._database_url(self.postgres_user, self.postgres_password)

    @property
    def api_database_url(self) -> str:
        """What the API connects with: the application role when one is configured, the owner role otherwise."""
        if self.app_db_user and self.app_db_password:
            return self._database_url(self.app_db_user, self.app_db_password)
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
