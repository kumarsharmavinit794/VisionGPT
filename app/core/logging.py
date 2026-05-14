import sys
import logging
import logging.handlers
from pathlib import Path
from app.core.config import settings

try:
    import structlog
    from structlog.stdlib import LoggerFactory
    from structlog.contextvars import merge_contextvars
except ModuleNotFoundError:
    structlog = None
    LoggerFactory = None
    merge_contextvars = None


class KeywordLogger:
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, event, *args, **kwargs):
        self._log(logging.DEBUG, event, *args, **kwargs)

    def info(self, event, *args, **kwargs):
        self._log(logging.INFO, event, *args, **kwargs)

    def warning(self, event, *args, **kwargs):
        self._log(logging.WARNING, event, *args, **kwargs)

    def error(self, event, *args, **kwargs):
        exc_info = kwargs.pop("exc_info", None)
        self._log(logging.ERROR, event, *args, exc_info=exc_info, **kwargs)

    def _log(self, level, event, *args, exc_info=None, **kwargs):
        context = f" {kwargs}" if kwargs else ""
        self._logger.log(level, f"{event}{context}", *args, exc_info=exc_info)


def add_request_id(_, __, event_dict):
    event_dict.setdefault("request_id", "-")
    return event_dict


def setup_logging():
    """Setup structured logging with structlog."""
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=[console_handler, file_handler],
        force=True,
    )

    if structlog is None:
        return KeywordLogger(logging.getLogger(settings.APP_NAME))

    processors = [
        merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.CallsiteParameterAdder([structlog.processors.CallsiteParameter.MODULE]),
        add_request_id,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.DEBUG:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.extend([structlog.processors.UnicodeDecoder(), structlog.processors.JSONRenderer()])

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger()


def get_logger(name: str = None):
    """Get a structured logger instance."""
    if structlog is None:
        return KeywordLogger(logging.getLogger(name or settings.APP_NAME))
    return structlog.get_logger(name)


# Initialize logger
logger = setup_logging()
