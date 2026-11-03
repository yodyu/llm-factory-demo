"""Single-attempt OpenAI-compatible I/O, with no provider payloads in errors.

The SDK is optional until an API transport is used. Raw response text passes
through the project's strict JSON boundary before semantic client validation.
"""

import inspect
import logging
import math
import re
from typing import Protocol

from contracts.base import strict_json_loads
from contracts.errors import ErrorCode, FactoryError

from .config import ModelEndpoint


_REASONS = frozenset(
    {
        "authentication",
        "authentication_failed",
        "permission_denied",
        "endpoint_or_model_not_found",
        "request_timeout",
        "request_conflict",
        "rate_limit",
        "rate_limited",
        "provider_unavailable",
        "request_rejected",
        "timeout",
        "connection_failed",
        "invalid_response",
        "transport_failed",
        "invalid_json_response",
        "sdk_unavailable",
        "sdk_configuration_invalid",
        "transport_close_failed",
        "configuration_missing",
        "explicit_mock_required",
        "transport_mode_mismatch",
        "profile_mismatch",
        "version_not_supported",
        "task_profile_mismatch",
        "credential_content_rejected",
        "call_id_invalid",
        "timeout_invalid",
        "operation_in_flight_or_unknown",
        "deadline_exceeded",
        "transport_error",
        "response_invalid",
        "usage_invalid",
        "completion_incomplete",
        "text_response_required",
        "messages_invalid",
        "embedding_model_mismatch",
        "embedding_count_mismatch",
        "embedding_index_invalid",
        "embedding_dimension_mismatch",
        "embedding_values_invalid",
        "embedding_zero_norm",
        "texts_invalid",
        "structured_output_invalid",
        "empty_generation_text",
        "mock_script_exhausted",
        "dimension_probe_requires_preparation",
    }
)


class ModelCallError(FactoryError):
    """Only stable, allowlisted metadata crosses the provider error boundary."""

    def __init__(
        self,
        code: ErrorCode,
        reason: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        outcome_unknown: bool = False,
        validation_issues: list[dict[str, str]] | None = None,
    ):
        # Custom transports pass through the same allowlist as the SDK adapter.
        # Free-form exception text is never suitable for a report or artifact.
        if type(reason) is not str or reason not in _REASONS:
            reason, retryable, outcome_unknown = "transport_error", False, True
        code = code if isinstance(code, ErrorCode) else ErrorCode.MODEL_ERROR
        self.reason = reason
        self.http_status = (
            http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        )
        self.retryable = retryable is True
        self.outcome_unknown = outcome_unknown is True
        self.validation_issues = [
            {"field": item["field"], "type": item["type"],
             **({"path": item["path"]} if isinstance(item.get("path"), str)
                and re.fullmatch(r"\$|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]{1,7}\])*", item["path"])
                and len(item["path"]) <= 256 else {})}
            for item in (validation_issues or [])[:12]
            if isinstance(item, dict)
            and isinstance(item.get("field"), str)
            and isinstance(item.get("type"), str)
            and re.fullmatch(r"\$|[A-Za-z_][A-Za-z0-9_]{0,79}", item["field"])
            and re.fullmatch(r"[a-z_]{1,80}", item["type"])
        ]
        super().__init__(code, f"{code.value}: {reason}")


class Transport(Protocol):
    async def chat(self, *, messages: list[dict[str, str]], model: str, timeout: float) -> dict: ...
    async def embed(self, *, texts: list[str], model: str, timeout: float) -> dict: ...


def _silence_request_loggers() -> None:
    # OPENAI_LOG=debug can otherwise expose prompts and authorization headers.
    prefixes = ("openai", "httpx", "httpcore", "httpx2", "httpcore2")
    names = set(prefixes)
    names.update(
        name
        for name in logging.Logger.manager.loggerDict
        if any(name.startswith(prefix + ".") for prefix in prefixes)
    )
    for name in names:
        logger = logging.getLogger(name)
        logger.disabled = True
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)


def _finite_json(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_json(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    return True


def _map_provider_error(error: Exception) -> ModelCallError:
    # Inspect types/status only: never str(error), response text, headers or URLs.
    name = type(error).__name__
    status = getattr(error, "status_code", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    if name == "APITimeoutError" or isinstance(error, TimeoutError):
        return ModelCallError(
            ErrorCode.MODEL_TIMEOUT, "timeout", retryable=True, outcome_unknown=True
        )
    if status is not None:
        reason = {
            401: "authentication_failed",
            403: "permission_denied",
            404: "endpoint_or_model_not_found",
            408: "request_timeout",
            409: "request_conflict",
            429: "rate_limited",
        }.get(status, "provider_unavailable" if status >= 500 else "request_rejected")
        return ModelCallError(
            ErrorCode.MODEL_ERROR,
            reason,
            http_status=status,
            retryable=status in {408, 409, 429} or status >= 500,
            outcome_unknown=status == 408,
        )
    if name in {
        "APIConnectionError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
    }:
        return ModelCallError(
            ErrorCode.MODEL_ERROR, "connection_failed", retryable=True, outcome_unknown=True
        )
    if name in {"APIResponseValidationError", "JSONDecodeError", "UnicodeDecodeError"}:
        return ModelCallError(
            ErrorCode.MODEL_OUTPUT_INVALID, "invalid_response", outcome_unknown=False
        )
    return ModelCallError(ErrorCode.MODEL_ERROR, "transport_failed", outcome_unknown=True)


class OpenAITransport:
    """One SDK attempt per call. Repeated attempts belong to the budgeted client."""

    mode = "api"

    def __init__(self, endpoint: ModelEndpoint, *, client=None):
        self._endpoint = endpoint
        self._client = client
        self._owns_client = client is None

    def _sdk(self):
        if self._client is None:
            _silence_request_loggers()
            error = None
            try:
                from openai import AsyncOpenAI
            except ImportError:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "sdk_unavailable")
            if error is not None:
                raise error from None
            _silence_request_loggers()
            try:
                self._client = AsyncOpenAI(
                    base_url=self._endpoint.base_url,
                    api_key=self._endpoint.api_key.get_secret_value(),
                    max_retries=0,
                )
            except Exception:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "sdk_configuration_invalid")
            if error is not None:
                raise error from None
        _silence_request_loggers()
        return self._client

    async def _request(self, kind: str, **arguments) -> dict:
        error = None
        try:
            client = self._sdk()
            # Do not trust retry defaults even on a caller-supplied SDK client.
            client = client.with_options(max_retries=0, timeout=arguments.pop("timeout"))
            if kind == "chat":
                response = await client.chat.completions.with_raw_response.create(**arguments)
            else:
                response = await client.embeddings.with_raw_response.create(**arguments)
            raw = response.text
            if callable(raw):
                raw = raw()
            if inspect.isawaitable(raw):
                raw = await raw
            try:
                parsed = strict_json_loads(raw)
                if not isinstance(parsed, dict) or not _finite_json(parsed):
                    raise ValueError
            except (ValueError, TypeError, UnicodeError, RecursionError):
                error = ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, "invalid_json_response")
            else:
                return parsed
        except ModelCallError as exc:
            # An injected SDK can raise a ModelCallError with a provider error
            # already attached as __context__. Never propagate that object.
            error = ModelCallError(
                exc.code,
                exc.reason,
                http_status=exc.http_status,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            )
        except Exception as exc:
            error = _map_provider_error(exc)
        # Raise outside the provider except block so traceback chaining cannot
        # retain a provider exception with private request or response content.
        raise error from None

    async def chat(self, *, messages: list[dict[str, str]], model: str, timeout: float) -> dict:
        return await self._request(
            "chat", messages=messages, model=model, timeout=timeout, stream=False
        )

    async def embed(self, *, texts: list[str], model: str, timeout: float) -> dict:
        return await self._request(
            "embedding", input=texts, model=model, timeout=timeout, encoding_format="float"
        )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            client, self._client = self._client, None
            error = None
            try:
                await client.close()
            except Exception:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "transport_close_failed")
            if error is not None:
                raise error from None

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> "OpenAITransport":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()
