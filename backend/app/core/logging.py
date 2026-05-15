import logging
import os


def configure_logging() -> None:
    """Configure root logger to emit JSON lines for Loki ingestion."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]
        handler = logging.StreamHandler()
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        root = logging.getLogger()
        root.handlers = [handler]
        root.setLevel(log_level)
    except ImportError:
        logging.basicConfig(level=log_level)
