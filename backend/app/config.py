"""Application configuration with environment-variable overrides."""

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = (
    Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Research Agent"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = False

    database_path: Path = Path("data/research_agent.sqlite3")

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi4-mini"
    ollama_connect_timeout: float = Field(default=5.0, gt=0)
    ollama_read_timeout: float = Field(default=120.0, gt=0)
    ollama_max_retries: int = Field(default=2, ge=0, le=10)
    ollama_context_window: int = Field(default=8192, ge=512)
    ollama_max_input_chars: int = Field(default=24000, ge=1000)
    ollama_temperature: float = Field(default=0.2, ge=0, le=2)

    openalex_api_key: str | None = None
    scholarly_email: str | None = None
    crossref_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    literature_per_source: int = Field(default=8, ge=1, le=50)
    literature_max_results: int = Field(default=50, ge=1, le=200)
    literature_cache_path: Path = Path("data/source-cache")

    upload_path: Path = Path("data/uploads")
    experiment_artifact_path: Path = Path("data/experiment-artifacts")
    export_path: Path = Path("exports")
    training_records_path: Path = Path("data/training/feedback.jsonl")
    training_path: Path = Path("data/training")
    feedback_source_salt: str | None = Field(default=None, min_length=16)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def resolved_database_path(self) -> Path:
        path = self.database_path
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def frontend_dir(self) -> Path:
        return PROJECT_ROOT / "frontend"

    def resolve_project_path(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def resolved_upload_path(self) -> Path:
        return self.resolve_project_path(self.upload_path)

    @property
    def resolved_literature_cache_path(self) -> Path:
        return self.resolve_project_path(self.literature_cache_path)

    @property
    def resolved_experiment_artifact_path(self) -> Path:
        return self.resolve_project_path(self.experiment_artifact_path)

    @property
    def resolved_export_path(self) -> Path:
        return self.resolve_project_path(self.export_path)

    @property
    def resolved_training_records_path(self) -> Path:
        return self.resolve_project_path(self.training_records_path)

    @property
    def resolved_training_path(self) -> Path:
        return self.resolve_project_path(self.training_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
