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
    seed_demo_project: bool = True

    # Уровень корневого логгера приложения. Ниже INFO стоит опускать только при
    # отладке: DEBUG в SQLAlchemy очень многословен.
    log_level: str = "INFO"
    # JSON-строки в лог вместо человекочитаемых — на случай, если логи начнут
    # куда-то собираться. По умолчанию человекочитаемо: это локальный запуск.
    log_json: bool = False

    # Ключ шифрования можно задать явно. Иначе он один раз создаётся рядом с
    # локальными данными установки; в SQLite этот секрет не хранится.
    secret_key: str | None = None
    # Крупный структурный ответ (например, весь список вопросов экзамена)
    # у думающей модели легко выходит за минуту скрытых рассуждений.
    ai_timeout_seconds: float = 180.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tentex.sqlite"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def installation_secret_path(self) -> Path:
        return self.data_dir / "installation.secret"


settings = Settings()
