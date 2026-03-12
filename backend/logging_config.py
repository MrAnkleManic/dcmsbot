import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend import config

LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "%(message)s | extra=%(extra_data)s"
)


class EnsureExtraDataFilter(logging.Filter):
    """Guarantee log records always have `extra_data` for our formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "extra_data"):
            record.extra_data = {}
        return True


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    existing = next(
        (h for h in root.handlers if isinstance(h, RotatingFileHandler)),
        None,
    )
    handler = existing or RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    if not any(isinstance(f, EnsureExtraDataFilter) for f in handler.filters):
        handler.addFilter(EnsureExtraDataFilter())
    if existing is None:
        root.addHandler(handler)


def get_logger(name: str, extra: Optional[dict] = None) -> logging.LoggerAdapter:
    base_logger = logging.getLogger(name)
    if extra is None:
        extra = {}
    return logging.LoggerAdapter(base_logger, {"extra_data": extra})


setup_logging()
