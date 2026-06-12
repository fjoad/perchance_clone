from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from ..config import settings
from ..db import utc_now


_LOGGER_NAME = "companion.events"
_configured = False


def configure_event_logging() -> None:
    global _configured
    if _configured:
        return
    log_dir = settings.runtime_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        _configured = True
        return
    handler = RotatingFileHandler(
        log_dir / "app_events.jsonl",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _configured = True


def _safe_value(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_value(v, limit=limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_value(item, limit=limit) for item in value[:40]]
    if isinstance(value, tuple):
        return [_safe_value(item, limit=limit) for item in value[:40]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def log_event(event: str, **fields: Any) -> None:
    configure_event_logging()
    payload = {
        "ts": utc_now(),
        "event": event,
        **{key: _safe_value(value) for key, value in fields.items()},
    }
    logging.getLogger(_LOGGER_NAME).info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
