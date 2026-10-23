"""Logging to the console and to a daily log file, as in the 12-month project.

    LOG_DIRECTORY/transaction_review.log            today's log
    LOG_DIRECTORY/transaction_review.log.2026-10-22  earlier days, kept LOG_RETENTION_DAYS days

Every line says which account file it is about (the "review" field), so the lines of reviews that run at the
same time can be told apart. The log holds file names, transaction ids and amounts, never the AI's answer
text (unless LLM_LOG_ANSWERS=true) and never the Foundry headers.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s [%(review)s] %(name)s: %(message)s"
LOG_FILE_NAME = "transaction_review.log"

# The account file being reviewed. Set once per review (app/review/pipeline.py); asyncio copies it into the
# tasks the review starts, so every AI call and tool line carries it too.
current_review: ContextVar[str] = ContextVar("current_review", default="-")


class _ReviewField(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.review = current_review.get()
        return True


def setup_logging(log_directory: Path, retention_days: int) -> Path | None:
    """Console and daily file logging on the root logger. Safe to call twice. Returns the log file, or None
    when the folder cannot be written (the console log still works and the app still starts)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    if not any(type(h) is logging.StreamHandler for h in root.handlers):
        root.addHandler(_with_review_field(logging.StreamHandler(), formatter))

    path = log_directory / LOG_FILE_NAME
    if any(isinstance(h, TimedRotatingFileHandler) and Path(h.baseFilename) == path.resolve() for h in root.handlers):
        return path
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        handler = TimedRotatingFileHandler(path, when="midnight", backupCount=retention_days, encoding="utf-8")
    except OSError as exc:
        root.warning("The log file cannot be written at %s: %s", path, exc)
        return None
    root.addHandler(_with_review_field(handler, formatter))
    # Uvicorn's own logger does not pass its lines on to the root logger: add the file to it too, so a server
    # error is in the file. (Its per-request access lines stay on the console only.)
    logging.getLogger("uvicorn").addHandler(handler)
    return path


def _with_review_field(handler: logging.Handler, formatter: logging.Formatter) -> logging.Handler:
    handler.setFormatter(formatter)
    handler.addFilter(_ReviewField())
    return handler
