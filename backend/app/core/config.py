from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """全局配置。环境变量前缀 TTK_，同时读取项目根目录 .env。"""

    model_config = SettingsConfigDict(
        env_prefix="TTK_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "题题的库"
    debug: bool = True

    data_dir: Path = PROJECT_ROOT / "data"

    # LLM 接入：mock（离线占位） | openai_compat（OpenAI 兼容协议）
    llm_provider: str = "mock"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "ttk.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.db_dir, self.raw_dir, self.upload_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
