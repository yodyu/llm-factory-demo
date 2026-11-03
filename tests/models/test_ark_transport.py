"""Explicit generation adapter, exercised with controlled SDK responses."""
import asyncio
import json
import httpx
import pytest
from pydantic import SecretStr
from factory.models import ArkChatTransport, OpenAITransport
from factory.models.config import ModelEndpoint
from factory.models.transport import ModelCallError

@pytest.fixture
def endpoint():
    return ModelEndpoint(base_url="https://example.invalid/prefix/api/v3", api_key=SecretStr("test-private-key"))


def test_ark_chat_options_are_explicit_and_default_openai_is_unchanged(endpoint):
    openai = pytest.importorskip("openai")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"model": "test-model"})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            sdk = openai.AsyncOpenAI(base_url=endpoint.base_url, api_key=endpoint.api_key.get_secret_value(),
                                     max_retries=5, http_client=http)
            for kind in (ArkChatTransport, OpenAITransport):
                await kind(endpoint, client=sdk).chat(messages=[{"role": "user", "content": "synthetic"}],
                                                      model="test-model", timeout=2.5)

    asyncio.run(exercise())
    ark, plain = [json.loads(request.content) for request in requests]
    assert ark["thinking"] == {"type": "disabled"} and ark["max_completion_tokens"] == 8192
    assert ark["stream"] is False
    assert "thinking" not in plain and "max_completion_tokens" not in plain
    assert all(request.url.path == "/prefix/api/v3/chat/completions" for request in requests)
    assert all(value == 2.5 for request in requests for value in request.extensions["timeout"].values())

def test_ark_chat_does_not_inherit_sdk_retry_budget(endpoint):
    openai = pytest.importorskip("openai")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "fixture-provider-key"}})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            sdk = openai.AsyncOpenAI(base_url=endpoint.base_url, api_key=endpoint.api_key.get_secret_value(),
                                     max_retries=5, http_client=http)
            await ArkChatTransport(endpoint, client=sdk).chat(messages=[{"role": "user", "content": "synthetic"}],
                                                             model="test-model", timeout=2.5)

    with pytest.raises(ModelCallError) as caught:
        asyncio.run(exercise())
    assert len(requests) == 1 and caught.value.reason == "rate_limited"
    assert "fixture-provider-key" not in str(caught.value)
