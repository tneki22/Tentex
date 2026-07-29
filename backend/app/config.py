from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Настройки берутся из переменных окружения, префикс TENTEX_."""

    model_config = SettingsConfigDict(env_prefix="TENTEX_", env_file=".env", extra="ignore")

    # Куда кладём базу и файловое хранилище. §23 требований: SQLite одним файлом,
    # растры и аудио — каталогом рядом, в базе только пути и хеши.
    data_dir: Path = PROJECT_ROOT / "data"

    # Откуда ходит фронтенд в режиме разработки.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tentex.sqlite"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"


settings = Settings()
