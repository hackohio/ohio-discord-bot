"""Shared logging configuration for the event services."""

import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIRECTORY = Path("logs")
_SECRET_VALUE = re.compile(
    r"""(?i)(api[-_ ]?key|authorization|password|token|secret)(\s*[:=]\s*)"""
    r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;)\]}"']+)"""
)
LOG_FORMAT = "%(asctime)s %(levelname)s %(processName)s %(name)s %(message)s"


class RedactingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return (
            datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds")
        )

    def format(self, record):
        return _SECRET_VALUE.sub(r"\1=REDACTED", super().format(record))


class ConsoleFormatter(RedactingFormatter):
    """Add level colors to interactive console output only."""

    _COLORS = {
        logging.DEBUG: "\033[2m",
        logging.INFO: "\033[36m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, *args, use_color=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_color = (
            use_color
            if use_color is not None
            else sys.stderr.isatty() and "NO_COLOR" not in os.environ
        )

    def format(self, record):
        message = super().format(record)
        if not self.use_color:
            return message
        color = self._COLORS.get(record.levelno)
        if not color:
            return message
        return message.replace(
            record.levelname,
            f"{color}{record.levelname}{self._RESET}",
            1,
        )


def configure_logging(service_name):
    """Configure one retained file and operator stderr for this process."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter(LOG_FORMAT)

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
    console_handler.setFormatter(ConsoleFormatter(LOG_FORMAT))

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
        force=True,
    )

    for name in ("discord", "waitress", "werkzeug", "flask.app"):
        dependency = logging.getLogger(name)
        dependency.handlers.clear()
        dependency.propagate = True
