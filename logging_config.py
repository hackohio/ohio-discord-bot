"""Shared logging configuration for the event services."""

import logging
import os
import re
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIRECTORY = Path("logs")
_SECRET_VALUE = re.compile(
    r"""(?i)(api[-_ ]?key|authorization|password|token|secret)(\s*[:=]\s*)"""
    r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;)\]}"']+)"""
)


class RedactingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return (
            datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds")
        )

    def format(self, record):
        return _SECRET_VALUE.sub(r"\1=REDACTED", super().format(record))


def configure_logging(service_name):
    """Configure one retained file and operator stderr for this process."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter(
        "%(asctime)s %(levelname)s %(processName)s %(name)s %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        LOG_DIRECTORY / f"{service_name}.log",
        when="midnight",
        backupCount=0,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    console_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
        force=True,
    )

    for name in ("discord", "waitress", "werkzeug", "flask.app"):
        dependency = logging.getLogger(name)
        dependency.handlers.clear()
        dependency.propagate = True
