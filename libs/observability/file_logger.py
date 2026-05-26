"""log4net-style rotating file logger for ClaimGPT activity & failure tracking.

Designed for use by upload / pipeline endpoints that need a durable on-disk
audit trail outside the structured DB audit log, e.g. claim uploads.

Default behaviour
-----------------
* Writes to ``<repo_root>/logs/<filename>`` (auto-creates the directory).
* Override the directory with the ``CLAIMGPT_LOG_DIR`` environment variable.
* Format mirrors log4net::
      2026-05-11 15:55:01,123 [INFO ] [ingress.upload] [claim=...] message
* Rotates at 10 MB, keeps 5 backups (``claim_uploads.txt.1`` … ``.5``).
* Does **not** propagate to the root logger, so it stays separate from the
  console / observability stack.

Usage
-----
    from libs.observability.file_logger import get_file_logger

    upload_log = get_file_logger("ingress.upload", "claim_uploads.txt")
    upload_log.info("upload received | claim=%s files=%d", claim_id, n)
    upload_log.exception("upload failed | claim=%s", claim_id)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

_LOG_FORMAT = (
    "%(asctime)s [%(levelname)-5s] [%(name)s] %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5

_lock = Lock()
_loggers: dict[str, logging.Logger] = {}


def _resolve_log_dir(log_dir: str | os.PathLike[str] | None) -> Path:
    if log_dir is not None:
        target = Path(log_dir)
    else:
        env = os.environ.get("CLAIMGPT_LOG_DIR")
        if env:
            target = Path(env)
        else:
            # repo_root = <this file>/../../../  -> /libs/observability/file_logger.py
            target = Path(__file__).resolve().parents[2] / "logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_file_logger(
    name: str,
    filename: str = "activity.txt",
    *,
    log_dir: str | os.PathLike[str] | None = None,
    level: int | str = logging.INFO,
) -> logging.Logger:
    """Return a singleton rotating-file logger for *name*.

    Subsequent calls with the same *name* return the same logger and do not
    add duplicate handlers.
    """
    cache_key = f"{name}::{filename}"
    with _lock:
        cached = _loggers.get(cache_key)
        if cached is not None:
            return cached

        logger = logging.getLogger(f"claimgpt.file.{name}")
        logger.setLevel(level if isinstance(level, int) else level.upper())
        logger.propagate = False  # keep this stream out of the console pipeline

        # Remove any pre-existing handlers we previously attached (defensive
        # against module reloads under uvicorn --reload).
        for h in list(logger.handlers):
            if getattr(h, "_claimgpt_file_logger", False):
                logger.removeHandler(h)

        path = _resolve_log_dir(log_dir) / filename
        handler = RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        handler._claimgpt_file_logger = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

        _loggers[cache_key] = logger
        return logger
