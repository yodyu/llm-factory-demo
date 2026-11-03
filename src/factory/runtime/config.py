"""Runtime-only settings. Importing this module never reads environment files."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .security import SecretGuard


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    runtime_dir: Path = Path(".runtime")
    model_mode: str = "api"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("model_mode")
    @classmethod
    def mode(cls, value):
        if value not in ("api", "mock"):
            raise ValueError("model mode must be api or mock")
        return value

    @field_validator("llm_base_url", "embedding_base_url")
    @classmethod
    def endpoint(cls, value):
        from urllib.parse import urlsplit

        if value is not None:
            url = urlsplit(value)
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("API base URL must not embed credentials, query or fragment")
        return value

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        names = {
            "runtime_dir": "FACTORY_RUNTIME_DIR",
            "model_mode": "FACTORY_MODEL_MODE",
            "llm_base_url": "LLM_BASE_URL",
            "llm_model": "LLM_MODEL",
            "llm_api_key": "LLM_API_KEY",
            "embedding_base_url": "EMBEDDING_BASE_URL",
            "embedding_model": "EMBEDDING_MODEL",
            "embedding_api_key": "EMBEDDING_API_KEY",
        }
        return cls(**{key: environ[name] for key, name in names.items() if name in environ})

    def secret_guard(self) -> SecretGuard:
        return SecretGuard(
            tuple(
                key.get_secret_value() for key in (self.llm_api_key, self.embedding_api_key) if key
            )
        )
