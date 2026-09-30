from pathlib import Path

from pydantic import Field
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
    # Исходная запись устной попытки хранится ограниченное время; текст остаётся.
    oral_audio_retention_days: int = Field(default=30, ge=1, le=3650)
    # Typst живёт только в worker-образе; путь можно подменить в локальном smoke.
    typst_binary: Path = Path("typst")
    # Модель локальной расшифровки аудио (faster-whisper). Читают и воркер, и API:
    # первый — чтобы загрузить веса, второй — чтобы подписать её в интерфейсе.
    whisper_model: str = "small"

    # Фоновые задачи делят один процесс, но не один слот: локальная обработка
    # ограничена железом, облачный разбор — сетью, остальные роли ИИ — провайдером.
    worker_local_concurrency: int = Field(default=1, ge=1, le=32)
    worker_cloud_concurrency: int = Field(default=2, ge=1, le=32)
    worker_ai_concurrency: int = Field(default=8, ge=1, le=32)
    retrieval_model_url: str = "http://retrieval-model:8010"
    # Постоянные SQLite-соединения API. 0 — новое соединение на каждую сессию:
    # так работает воркер, чтобы после восстановления копии ни одно соединение
    # не держало подменённый файл. У API пул сохраняет кэш страниц между
    # запросами; на bind mount с Windows повторное чтение из кэша в десятки раз
    # быстрее чтения с диска. `restore` сам закрывает пул перед подменой.
    sqlite_pool_size: int = Field(default=0, ge=0, le=32)
    # Локальный SearXNG чата «Поиск в интернете». В Docker api ходит в сервис
    # `searxng`; при запуске бэкенда на хосте — в порт, проброшенный на localhost.
    searxng_url: str = "http://localhost:8888"
    # Защитные пределы переносимых архивов. Сам архив может быть большим,
    # но распакованный объём ограничен отдельно от размера HTTP-загрузки.
    transfer_upload_max_bytes: int = Field(default=25 * 1024**3, ge=1024**2)
    transfer_unpacked_max_bytes: int = Field(default=100 * 1024**3, ge=1024**2)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tentex.sqlite"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def installation_secret_path(self) -> Path:
        return self.data_dir / "installation.secret"

    @property
    def typst_package_cache_dir(self) -> Path:
        """Постоянный локальный кэш подтверждённых пакетов Typst."""
        path = self.data_dir / "typst-packages"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def embedding_models_dir(self) -> Path:
        """Общий кэш безопасно загруженных HF-моделей retrieval service."""
        path = self.data_dir / "models" / "embeddings"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def default_backup_dir(self) -> Path:
        """Каталог управляемых копий; не входит в `storage/` и архивы."""
        return self.data_dir / "backups"

    @property
    def transfer_dir(self) -> Path:
        """Машинный staging импортов и временных экспортов."""
        return self.data_dir / "transfers"

    @property
    def maintenance_path(self) -> Path:
        """Координация API и worker при снимке/замене самой SQLite."""
        return self.data_dir / "maintenance.json"

    @property
    def restore_journal_path(self) -> Path:
        """Журнал атомарной замены, читаемый до открытия базы."""
        return self.data_dir / "restore-journal.json"

    @property
    def diagnostics_dir(self) -> Path:
        """Журнал сбоев и пульс воркера: читаются, даже когда SQLite не отвечает."""
        return self.data_dir / "diagnostics"


settings = Settings()
