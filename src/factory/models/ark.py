"""Explicit Ark transports; callers bind ``identity`` into public profiles.

Reference: https://docs.volcengine.com/docs/ark/multimodal-vectorization-api
Instructions: https://docs.volcengine.com/docs/ark/vectorization

An Ark multimodal input list describes ONE combined sample, not a text batch.
This adapter accepts exactly one text per call, therefore one ledger operation
always corresponds to at most one HTTP request. It never splits or retries.
"""

from copy import deepcopy
import math

from contracts import ErrorCode
from contracts.base import strict_json_loads

from .config import ModelEndpoint
from .transport import (
    ModelCallError,
    OpenAITransport,
    _finite_json,
    _map_provider_error,
    _silence_request_loggers,
)


ARK_STS_INSTRUCTIONS = (
    "Target_modality: text.\nInstruction:Retrieve semantically similar text\nQuery:"
)
ARK_MULTIMODAL_IDENTITY = {
    "protocol": "ark-text-sts/1",
    "endpoint_suffix": "embeddings/multimodal",
    "instructions": ARK_STS_INSTRUCTIONS,
    "encoding_format": "float",
    "input_texts_per_request": 1,
    "dimensions": "provider_default",
}
ARK_CHAT_IDENTITY = {
    "protocol": "ark-chat-json/1",
    "max_completion_tokens": 8192,
    "thinking": {"type": "disabled"},
    "stream": False,
}


class ArkChatTransport(OpenAITransport):
    """Opt-in short-latency JSON generation; default OpenAI behavior is intact."""

    @property
    def identity(self):
        return deepcopy(ARK_CHAT_IDENTITY)

    async def chat(self, *, messages, model, timeout):
        return await self._request(
            "chat",
            messages=messages,
            model=model,
            timeout=timeout,
            stream=False,
            max_completion_tokens=ARK_CHAT_IDENTITY["max_completion_tokens"],
            extra_body={"thinking": deepcopy(ARK_CHAT_IDENTITY["thinking"])},
        )


class ArkMultimodalTransport:
    """Text-only STS adapter with the same fixed instructions on both sides.

    ``identity`` must be included in the caller's versioned profile identity;
    changing instructions changes the vector space and requires a new index.
    Inject an HTTPX client only for controlled transport tests. Production uses
    HTTPX's zero-retry default transport and session proxy environment settings.
    Credentials remain runtime-only and redirects are explicitly disabled.
    """

    mode = "api"

    def __init__(self, endpoint: ModelEndpoint, *, client=None):
        self._endpoint, self._client = endpoint, client
        self._owns_client = client is None

    @property
    def identity(self):
        return deepcopy(ARK_MULTIMODAL_IDENTITY)

    def _http(self):
        _silence_request_loggers()
        if self._client is None:
            error = None
            try:
                import httpx

                # AsyncHTTPTransport defaults to retries=0. Let AsyncClient
                # construct it so HTTP_PROXY/HTTPS_PROXY/NO_PROXY still apply.
                self._client = httpx.AsyncClient(follow_redirects=False)
            except ImportError:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "sdk_unavailable")
            except Exception:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "sdk_configuration_invalid")
            if error is not None:
                raise error from None
        return self._client

    @staticmethod
    def _status_error(status):
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

    async def embed(self, *, texts, model, timeout):
        if (
            type(texts) is not list
            or len(texts) != 1
            or type(texts[0]) is not str
            or not texts[0].strip()
        ):
            raise ModelCallError(ErrorCode.INVALID_INPUT, "texts_invalid")
        if type(model) is not str or not model.strip():
            raise ModelCallError(ErrorCode.INVALID_INPUT, "embedding_model_mismatch")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ModelCallError(ErrorCode.INVALID_INPUT, "timeout_invalid")
        error = None
        try:
            response = await self._http().post(
                self._endpoint.base_url.rstrip("/") + "/embeddings/multimodal",
                headers={
                    "Authorization": "Bearer " + self._endpoint.api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "encoding_format": "float",
                    "instructions": ARK_STS_INSTRUCTIONS,
                    "input": [{"type": "text", "text": texts[0]}],
                },
                timeout=timeout,
                follow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                error = self._status_error(response.status_code)
            else:
                try:
                    raw = strict_json_loads(response.content)
                    if (
                        not isinstance(raw, dict)
                        or not _finite_json(raw)
                        or not isinstance(raw.get("model"), str)
                        or not raw["model"].strip()
                        or not isinstance(raw.get("data"), dict)
                        or not isinstance(raw["data"].get("embedding"), list)
                    ):
                        raise ValueError
                    usage = raw.get("usage")
                    if usage is not None and not isinstance(usage, dict):
                        raise ValueError
                    # Index zero is the one combined multimodal sample. Never
                    # pretend several input texts returned independent vectors.
                    return {
                        "model": raw["model"],
                        "data": [{"index": 0, "embedding": raw["data"]["embedding"]}],
                        "usage": {"prompt_tokens": usage.get("prompt_tokens")}
                        if usage is not None
                        else None,
                    }
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                    error = ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, "invalid_json_response")
        except ModelCallError as failure:
            error = ModelCallError(
                failure.code,
                failure.reason,
                http_status=failure.http_status,
                retryable=failure.retryable,
                outcome_unknown=failure.outcome_unknown,
            )
        except Exception as failure:
            # Inspect types only. Neither response bodies nor exception strings
            # (which can contain Authorization/input) cross this boundary.
            if type(failure).__name__ in {
                "ConnectTimeout",
                "ReadTimeout",
                "WriteTimeout",
                "PoolTimeout",
            }:
                error = ModelCallError(
                    ErrorCode.MODEL_TIMEOUT, "timeout", retryable=True, outcome_unknown=True
                )
            else:
                error = _map_provider_error(failure)
        raise error from None

    async def chat(self, **kwargs):
        raise ModelCallError(ErrorCode.INVALID_INPUT, "configuration_missing")

    async def aclose(self):
        if self._client is not None and self._owns_client:
            client, self._client = self._client, None
            error = None
            try:
                await client.aclose()
            except Exception:
                error = ModelCallError(ErrorCode.MODEL_ERROR, "transport_close_failed")
            if error is not None:
                raise error from None
