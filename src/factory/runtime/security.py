"""Defense in depth for structured persistence and task logging.

Explicit secret registration handles provider-specific key formats. Arbitrary
free text cannot be proven secret-free; callers must only persist allowlisted
public payloads/references and must not serialize provider exceptions wholesale.
"""

import logging
import re
from collections.abc import Mapping

from pydantic import SecretStr

_KEY = re.compile(
    r"(^|_)(api_key|password|secret|credential|authorization|access_token|refresh_token|private_key)(_|$)",
    re.I,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_ASSIGN = re.compile(r"(?i)\b(api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*[^\s,;\"']+")


class SecretGuard:
    def __init__(self, secrets: tuple[str, ...] = ()):
        self._secrets = tuple(value for value in secrets if value)

    def redact(self, text: str) -> str:
        for value in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return _ASSIGN.sub(
            lambda m: m.group(1) + "=[REDACTED]", _BEARER.sub("Bearer [REDACTED]", text)
        )

    def require_public(self, value: object) -> None:
        if isinstance(value, SecretStr):
            raise ValueError("secret value cannot be persisted")
        if isinstance(value, Mapping):
            for key, item in value.items():
                if _KEY.search(str(key)):
                    raise ValueError("credential field cannot be persisted")
                self.require_public(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.require_public(item)
        elif isinstance(value, str) and self.redact(value) != value:
            raise ValueError("credential content cannot be persisted")


class RedactingFormatter(logging.Formatter):
    """Redact after formatting, including exception tracebacks and interpolation."""

    def __init__(self, guard: SecretGuard):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.guard = guard

    def format(self, record: logging.LogRecord) -> str:
        return self.guard.redact(super().format(record))


def configure_logging(guard: SecretGuard, stream=None) -> logging.Logger:
    logger = logging.getLogger("llm_factory")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(guard))
    logger.addHandler(handler)
    return logger
