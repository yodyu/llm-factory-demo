"""Capability checks do not infer one endpoint's support from the other."""

import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from contracts import ErrorCode, FactoryError
from contracts.ports import ModelResponse
from factory.models.checks import check_embedding, check_generation, validate_structured
from factory.models.clients import LLMClient
from factory.models.config import LLMProfile
from factory.models.testing import ScriptedTransport
from factory.models.transport import ModelCallError


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: int


def test_structured_accepts_exact_schema():
    assert validate_structured('{"answer": 7}', Answer).answer == 7


@pytest.mark.parametrize("text", [
    '{"answer":1,"answer":2}', '{"answer":NaN}',
    '```json\n{"answer":1}\n```', '{"answer":1} extra',
    '{"answer":"1"}', '{"answer":true}', '{"answer":1,"extra":1}',
    '{"answer":"password=super-secret"}', '[1]', '',
])
def test_structured_rejects_invalid_output_without_echo(text):
    with pytest.raises(FactoryError) as caught:
        validate_structured(text, Answer)
    assert caught.value.code == ErrorCode.MODEL_OUTPUT_INVALID
    assert "super-secret" not in str(caught.value)
    assert "answer" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert caught.value.__context__ is None


def test_mock_transport_is_explicit_and_records_only_safe_summaries():
    fixture = {"data": [{"embedding": [1.0, 2.0]}]}
    scripted = ScriptedTransport([fixture])
    response = asyncio.run(scripted.embed(texts=["password=private"], model="embedding-fixture", timeout=3.0))
    response["data"][0]["embedding"][0] = 99
    assert fixture["data"][0]["embedding"][0] == 1.0
    assert scripted.mode == "mock"
    assert scripted.calls == [{"operation": "embed", "model": "embedding-fixture", "input_count": 1, "timeout": 3.0}]
    assert "private" not in repr(scripted) + json.dumps(scripted.calls)
    with pytest.raises(FactoryError) as caught:
        asyncio.run(scripted.chat(messages=[], model="text-fixture", timeout=1.0))
    assert caught.value.code == ErrorCode.MODEL_ERROR


def test_mock_script_can_raise_controlled_transport_error():
    failure = FactoryError(ErrorCode.MODEL_TIMEOUT, "fixture timeout")
    scripted = ScriptedTransport([failure])
    with pytest.raises(FactoryError) as caught:
        asyncio.run(scripted.chat(messages=[], model="text-fixture", timeout=1.0))
    assert caught.value is failure
    assert len(scripted.calls) == 1


def test_mock_client_requires_and_uses_explicit_script(model_runtime, chat_response):
    task, ledger, artifacts = model_runtime
    task = task.model_copy(update={"task_id": "explicit-mock-task", "model_mode": "mock"})
    ledger.create_task(task)
    profile = LLMProfile(profile_id=task.model_profile_id, service_id="mock-service",
                         model="fixture-chat-model", mode="mock")
    with pytest.raises(FactoryError):
        LLMClient(profile, None, ledger, artifacts)
    transport = ScriptedTransport([chat_response])
    client = LLMClient(profile, None, ledger, artifacts, transport=transport)
    result = asyncio.run(check_generation(client, task.task_id, "mock-check"))
    assert result.status == "passed"
    assert len(transport.calls) == 1


class GenerationFixture:
    profile = SimpleNamespace(profile_id="chat-check")

    def __init__(self, error=None, text="Hello"):
        self.error = error
        self.text = text
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ModelResponse(call_id=request.call_id, text=self.text,
                             actual_model="fixture-chat", input_tokens=None,
                             output_tokens=None, response_ref="artifact-fixture")


class EmbeddingFixture:
    profile = SimpleNamespace(profile_id="embedding-check")

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def embed(self, task_id, call_id, texts, profile_id):
        self.calls.append((task_id, call_id, texts, profile_id))
        if self.error:
            raise self.error
        return SimpleNamespace(vectors=[[0.25, 0.5]])


def test_capability_checks_are_independent_and_use_no_private_input():
    generation = GenerationFixture()
    embedding = EmbeddingFixture(FactoryError(ErrorCode.MODEL_ERROR, "password=private"))
    chat_result = asyncio.run(check_generation(generation, "task-fixture", "check-chat"))
    embedding_result = asyncio.run(check_embedding(embedding, "task-fixture", "check-embedding"))
    assert chat_result.status == "passed"
    assert chat_result.response_ref == "artifact-fixture"
    assert embedding_result.status == "failed"
    assert embedding_result.error_code == "MODEL_ERROR"
    assert "private" not in json.dumps(asdict(embedding_result))
    assert len(generation.requests) == len(embedding.calls) == 1
    assert generation.requests[0].timeout_seconds == 10.0
    assert embedding.calls[0][3] == "embedding-check"


def test_generation_check_does_not_require_json_support():
    result = asyncio.run(check_generation(GenerationFixture(text="ordinary plain text"), "task", "call"))
    assert result.status == "passed"


def test_generation_failure_does_not_prevent_independent_embedding_check():
    generation = GenerationFixture(FactoryError(ErrorCode.MODEL_TIMEOUT, "password=private"))
    embedding = EmbeddingFixture()
    result = asyncio.run(check_generation(generation, "task", "chat-call"))
    assert result.status == "failed"
    assert result.error_code == "MODEL_TIMEOUT"
    assert asyncio.run(check_embedding(embedding, "task", "embed-call")).status == "passed"


def test_empty_generation_is_not_a_successful_capability_check():
    result = asyncio.run(check_generation(GenerationFixture(text="  "), "task", "call"))
    assert result.status == "failed"
    assert result.error_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("status,reason", [(401, "authentication_failed"), (404, "endpoint_or_model_not_found"),
                                          (429, "rate_limited")])
def test_check_retains_safe_failure_classification(status, reason):
    fixture = GenerationFixture(ModelCallError(ErrorCode.MODEL_ERROR, reason, http_status=status))
    result = asyncio.run(check_generation(fixture, "task", "call"))
    assert result.reason == reason
    assert result.http_status == status


def test_overflow_float_is_invalid_even_when_schema_allows_nonfinite():
    class Number(BaseModel):
        value: float

    with pytest.raises(ModelCallError) as caught:
        validate_structured('{"value":1e999}', Number)
    assert caught.value.code == ErrorCode.MODEL_OUTPUT_INVALID
