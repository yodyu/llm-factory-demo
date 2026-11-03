"""SDK boundary tests use synthetic responses and no external service."""

import asyncio
import json
import logging
import sys
import traceback
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError

from contracts.errors import ErrorCode, FactoryError
from factory.models.config import EmbeddingProfile, LLMProfile, ModelEndpoint
from factory.models.transport import ModelCallError, OpenAITransport
from factory.runtime.config import Settings


class FakeSDK:
    def __init__(self, response='{"model":"test-model"}'):
        self.response = response
        self.calls = []
        self.options = []
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            with_raw_response=SimpleNamespace(create=self.chat_create)))
        self.embeddings = SimpleNamespace(with_raw_response=SimpleNamespace(create=self.embed_create))

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    async def result(self):
        if isinstance(self.response, Exception):
            raise self.response
        return SimpleNamespace(text=self.response)

    async def chat_create(self, **kwargs):
        self.calls.append(("chat", kwargs))
        return await self.result()

    async def embed_create(self, **kwargs):
        self.calls.append(("embedding", kwargs))
        return await self.result()

    async def close(self):
        self.closed = True


@pytest.fixture
def endpoint():
    return ModelEndpoint(base_url="https://example.invalid/prefix/api", api_key=SecretStr("test-private-key"))


def run_chat(transport):
    return asyncio.run(transport.chat(messages=[{"role": "user", "content": "synthetic"}],
                                      model="test-model", timeout=2.0))


def test_endpoint_key_excluded_and_settings_independent():
    settings = Settings(llm_base_url="https://chat.example.invalid/path", llm_api_key=SecretStr("chat-key"),
                        embedding_base_url="https://embed.example.invalid/custom", embedding_api_key=SecretStr("embed-key"))
    llm = ModelEndpoint.from_settings(settings)
    vectors = ModelEndpoint.from_settings(settings, service="embedding")
    assert llm.base_url.endswith("/path") and vectors.base_url.endswith("/custom")
    assert "chat-key" not in repr(llm) and "api_key" not in llm.model_dump()
    assert "embed-key" not in vectors.model_dump_json()
    with pytest.raises(FactoryError):
        ModelEndpoint.from_settings(Settings())


@pytest.mark.parametrize("url", ["file:///tmp/model", "https://user:pass@example.invalid/api",
                                    "https://example.invalid/api?token=secret", "https://example.invalid/#key",
                                    "https://example.invalid:bad/api", " https://example.invalid/api"])
def test_endpoint_rejects_credential_and_invalid_addresses(url):
    with pytest.raises(ValidationError):
        ModelEndpoint(base_url=url, api_key=SecretStr("key"))


def test_profiles_preserve_service_model_dimensions_and_mode():
    llm = LLMProfile(profile_id="llm-v1", service_id="chat-service", model="vendor/deployment", mode="api")
    embedding = EmbeddingProfile(profile_id="embedding-v1", service_id="vectors-service", model="vector-model",
                                 dimensions=3, mode="mock")
    assert llm.text_processing_version == "plain-v1"
    assert embedding.distance == "cosine" and embedding.mode == "mock"
    with pytest.raises(ValidationError):
        EmbeddingProfile(**{**embedding.model_dump(), "dimensions": True})
    with pytest.raises(ValidationError):
        EmbeddingProfile(**{**embedding.model_dump(), "dimensions": 0})


def test_single_attempt_nonstreaming_prefix_and_float_vectors(endpoint, monkeypatch):
    sdk = FakeSDK()
    constructor = []

    def factory(**kwargs):
        constructor.append(kwargs)
        return sdk

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=factory))
    transport = OpenAITransport(endpoint)
    assert run_chat(transport) == {"model": "test-model"}
    asyncio.run(transport.embed(texts=["a", "b"], model="vector-model", timeout=3.0))
    assert constructor[0]["max_retries"] == 0
    assert constructor[0]["base_url"] == endpoint.base_url
    assert sdk.options == [{"max_retries": 0, "timeout": 2.0}, {"max_retries": 0, "timeout": 3.0}]
    assert sdk.calls[0][1]["stream"] is False
    assert sdk.calls[1][1] == {"input": ["a", "b"], "model": "vector-model", "encoding_format": "float"}
    asyncio.run(transport.aclose())
    assert sdk.closed


def test_injected_client_also_disables_retries_and_is_caller_owned(endpoint):
    sdk = FakeSDK()
    transport = OpenAITransport(endpoint, client=sdk)
    assert run_chat(transport)["model"] == "test-model"
    assert sdk.options == [{"max_retries": 0, "timeout": 2.0}]
    asyncio.run(transport.aclose())
    assert not sdk.closed


@pytest.mark.parametrize("raw", ['{"model":"a","model":"b"}', '{"v":NaN}', '{"v":Infinity}',
                                    '{"v":1e999}', '[1,2]', 'not-json', '{"nested":{"v":-1e999}}'])
def test_strict_raw_json_boundary(endpoint, raw):
    with pytest.raises(ModelCallError) as caught:
        run_chat(OpenAITransport(endpoint, client=FakeSDK(raw)))
    assert caught.value.code == ErrorCode.MODEL_OUTPUT_INVALID
    assert caught.value.outcome_unknown is False


@pytest.mark.parametrize("status,reason,retryable,unknown", [
    (401, "authentication_failed", False, False), (403, "permission_denied", False, False),
    (404, "endpoint_or_model_not_found", False, False), (429, "rate_limited", True, False),
    (408, "request_timeout", True, True), (500, "provider_unavailable", True, False),
])
def test_http_errors_are_distinct_without_provider_content(endpoint, status, reason, retryable, unknown):
    provider = RuntimeError("Bearer test-private-key request-body and provider-response")
    provider.status_code = status
    with pytest.raises(ModelCallError) as caught:
        run_chat(OpenAITransport(endpoint, client=FakeSDK(provider)))
    error = caught.value
    assert error.reason == reason and error.http_status == status
    assert error.retryable is retryable and error.outcome_unknown is unknown
    assert error.__cause__ is None and error.__context__ is None
    rendered = "".join(traceback.format_exception(error))
    assert "test-private-key" not in rendered and "provider-response" not in rendered


def test_timeout_is_unknown_and_never_retried(endpoint):
    sdk = FakeSDK(TimeoutError("secret-provider-timeout"))
    with pytest.raises(ModelCallError) as caught:
        run_chat(OpenAITransport(endpoint, client=sdk))
    assert caught.value.code == ErrorCode.MODEL_TIMEOUT and caught.value.outcome_unknown
    assert len(sdk.calls) == 1 and "secret-provider" not in str(caught.value)


def test_sdk_and_http_request_logging_suppressed_even_when_enabled(endpoint, caplog):
    caplog.set_level(logging.DEBUG)
    for name in ("openai", "openai._base_client", "httpx", "httpcore.connection"):
        logger = logging.getLogger(name)
        logger.disabled = False
        logger.setLevel(logging.DEBUG)
    run_chat(OpenAITransport(endpoint, client=FakeSDK(json.dumps({"model": "test-model"}))))
    for name in ("openai", "openai._base_client", "httpx", "httpcore.connection"):
        logging.getLogger(name).warning("Bearer test-private-key request and response")
    assert "test-private-key" not in caplog.text


def test_installed_sdk_uses_expected_urls_headers_and_json_payloads(endpoint):
    """Exercise the real SDK HTTP layer against an in-memory HTTP transport."""
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b'{"model":"test-model"}', headers={"content-type": "application/json"})

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        sdk = openai.AsyncOpenAI(base_url=endpoint.base_url,
                                 api_key=endpoint.api_key.get_secret_value(), max_retries=5,
                                 http_client=http_client)
        try:
            transport = OpenAITransport(endpoint, client=sdk)
            await transport.chat(messages=[{"role": "user", "content": "synthetic"}], model="test-model", timeout=2.0)
            await transport.embed(texts=["synthetic"], model="vector-model", timeout=2.0)
        finally:
            await sdk.close()

    asyncio.run(exercise())
    assert [request.url.path for request in requests] == ["/prefix/api/chat/completions", "/prefix/api/embeddings"]
    assert all(request.headers["authorization"] == "Bearer test-private-key" for request in requests)
    assert json.loads(requests[0].content)["stream"] is False
    assert json.loads(requests[1].content)["encoding_format"] == "float"


@pytest.mark.parametrize("status", [429, 500])
def test_installed_sdk_error_never_uses_its_default_retry_budget(endpoint, status):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    attempts = []

    def handle(request):
        attempts.append(request.url.path)
        return httpx.Response(status, json={"error": {"message": "private-provider-message test-private-key"}})

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        sdk = openai.AsyncOpenAI(base_url=endpoint.base_url,
                                 api_key=endpoint.api_key.get_secret_value(), max_retries=5,
                                 http_client=http_client)
        try:
            with pytest.raises(ModelCallError) as caught:
                await OpenAITransport(endpoint, client=sdk).chat(
                    messages=[{"role": "user", "content": "synthetic"}], model="test-model", timeout=2.0)
            error = caught.value
            assert error.http_status == status and error.retryable
            assert error.__cause__ is None and error.__context__ is None
            assert "private-provider-message" not in "".join(traceback.format_exception(error))
        finally:
            await sdk.close()

    asyncio.run(exercise())
    assert attempts == ["/prefix/api/chat/completions"]


def assert_sanitized_context(error):
    assert error.__cause__ is None and error.__context__ is None
    assert "private-provider-secret" not in "".join(traceback.format_exception(error))


def test_sdk_constructor_error_retains_no_provider_exception(endpoint, monkeypatch):
    def factory(**_kwargs):
        raise RuntimeError("private-provider-secret")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=factory))
    transport = OpenAITransport(endpoint)
    with pytest.raises(ModelCallError) as direct:
        transport._sdk()
    assert_sanitized_context(direct.value)
    with pytest.raises(ModelCallError) as wrapped:
        run_chat(transport)
    assert_sanitized_context(wrapped.value)
    assert wrapped.value.reason == "sdk_configuration_invalid"


def test_injected_model_error_is_cloned_without_existing_context(endpoint):
    try:
        raise RuntimeError("private-provider-secret")
    except RuntimeError:
        try:
            raise ModelCallError(ErrorCode.MODEL_ERROR, "connection_failed", outcome_unknown=True)
        except ModelCallError as original:
            provider_error = original
    assert provider_error.__context__ is not None
    with pytest.raises(ModelCallError) as caught:
        run_chat(OpenAITransport(endpoint, client=FakeSDK(provider_error)))
    assert caught.value is not provider_error
    assert_sanitized_context(caught.value)
    assert caught.value.reason == "connection_failed" and caught.value.outcome_unknown


def test_sdk_close_failure_retains_no_provider_exception(endpoint, monkeypatch):
    class FailingClose(FakeSDK):
        async def close(self):
            raise RuntimeError("private-provider-secret")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=lambda **_kwargs: FailingClose()))
    transport = OpenAITransport(endpoint)
    run_chat(transport)
    with pytest.raises(ModelCallError) as caught:
        asyncio.run(transport.aclose())
    assert_sanitized_context(caught.value)
    assert caught.value.reason == "transport_close_failed"
