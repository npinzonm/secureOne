"""Logging operativo estructurado (JSON), separado de la auditoría (REQ-ERR-03).

Incluye un filtro que enmascara valores de claves sensibles para que nunca
lleguen a los logs contraseñas, tokens, cookies ni secretos.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_KEYS = re.compile(
    r"(password|passwd|secret|token|authorization|cookie|api[_-]?key)", re.IGNORECASE
)
_SENSITIVE_INLINE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|cookie|api[_-]?key)(\s*[=:]\s*)(\S+)"
)
REDACTED = "***"


def redact(value: object) -> object:
    """Enmascara recursivamente valores asociados a claves sensibles."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SENSITIVE_KEYS.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SENSITIVE_INLINE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "correlation_id": correlation_id_var.get(),
        }
        extra = getattr(record, "extra_data", None)
        if extra:
            payload["data"] = redact(extra)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
