"""Public, versioned model profiles and separately held runtime credentials."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator

from contracts.base import Contract, Identifier
from contracts.errors import ErrorCode, FactoryError
from factory.runtime.config import Settings


class LLMProfile(Contract):
    """A caller-assigned immutable identity; never includes an API endpoint/key."""

    profile_id: Identifier
    service_id: Identifier
    model: str = Field(min_length=1)
    mode: Literal["api", "mock"]
    text_processing_version: Literal["plain-v1"] = "plain-v1"

    @field_validator("model")
    @classmethod
    def nonempty_model(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("model identifier must not have surrounding whitespace")
        return value


class EmbeddingProfile(LLMProfile):
    dimensions: int = Field(gt=0)
    distance: Literal["cosine"] = "cosine"


class ModelEndpoint(Contract):
    """Runtime credentials are excluded from dumps and repr, even nested dumps."""

    base_url: str = Field(min_length=1)
    api_key: SecretStr = Field(exclude=True, repr=False)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            if (
                value != value.strip()
                or any(c.isspace() for c in value)
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            # Force validation of malformed ports without exposing the URL.
            _ = parsed.port
        except ValueError:
            raise ValueError(
                "base URL requires HTTP(S), without credentials, query or fragment"
            ) from None
        return value

    @field_validator("api_key")
    @classmethod
    def nonempty_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("nonempty runtime API key required")
        return value

    @classmethod
    def from_settings(
        cls, settings: Settings, service: Literal["llm", "embedding"] = "llm"
    ) -> "ModelEndpoint":
        if service not in {"llm", "embedding"}:
            raise FactoryError(ErrorCode.INVALID_INPUT, "unknown model service")
        base_url = getattr(settings, f"{service}_base_url")
        api_key = getattr(settings, f"{service}_api_key")
        if not base_url or api_key is None:
            raise FactoryError(ErrorCode.MODEL_ERROR, "model service is not configured")
        return cls(base_url=base_url, api_key=api_key)
