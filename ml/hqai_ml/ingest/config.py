import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class IngestParams(BaseModel):
    window_start: dt.date
    window_end: dt.date
    planned_dt_min: dt.date
    planned_dt_max: dt.date
    region_vote_min_share: float
    fuzzy_min_score: float
    fuzzy_min_sort_score: float
    day_hospital_code: str
    day_hospital_name: str


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    postgres_user: str = "hqai"
    postgres_password: str = "change-me"
    postgres_db: str = "hqai"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    duckdb_memory_limit: str = "4GB"

    raw_dir: Path = REPO_ROOT / "data" / "raw"
    processed_dir: Path = REPO_ROOT / "data" / "processed"
    reports_dir: Path = REPO_ROOT / "reports"
    configs_dir: Path = REPO_ROOT / "ml" / "configs"
    artifacts_dir: Path = REPO_ROOT / "artifacts"

    @property
    def pg_conninfo(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )

    def params(self) -> IngestParams:
        return IngestParams(**yaml.safe_load((self.configs_dir / "ingest.yaml").read_text(encoding="utf-8")))
