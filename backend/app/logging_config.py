import logging
from logging.config import dictConfig

from app.config import settings

_CONFIGURED = False


def configure_logging(level: str | None = None, *, json_logs: bool | None = None) -> None:
    """Настроить логирование один раз на процесс. Повторный вызов — no-op.

    Вызывается и из API (`create_app`), и из воркера (`worker.main`): у каждого
    свой процесс, поэтому конфиг нужен обоим, но внутри процесса — единожды.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved_level = (level or settings.log_level).upper()
    use_json = settings.log_json if json_logs is None else json_logs
    fmt = (
        '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        if use_json
        else "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    )
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": fmt}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["console"], "level": resolved_level},
            "loggers": {
                # SQLAlchemy на INFO печатает каждый SQL — держим на WARNING.
                "sqlalchemy.engine": {"level": "WARNING"},
                "uvicorn.access": {"level": resolved_level},
            },
        }
    )
    _CONFIGURED = True
    logging.getLogger("tentex").debug("logging configured at %s", resolved_level)
