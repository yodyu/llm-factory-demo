"""Client boundaries with real M00 ledger/artifacts and controlled transports."""

import asyncio

from copy import deepcopy

import json

import sqlite3

import pytest

from pydantic import BaseModel, ConfigDict, SecretStr

from contracts import ErrorCode, FactoryError

from contracts.ports import ModelRequest

from factory.models.clients import LLMClient

from factory.models.config import LLMProfile, ModelEndpoint

from factory.models.transport import ModelCallError

from factory.metrics.runtime import MetricsStore

class ControlledTransport:
    """An explicit compatible transport, never a fallback for a network error."""

    mode = "api"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        return self._next()

    async def embed(self, **kwargs):
        self.calls.append(("embed", kwargs))
        return self._next()

    def _next(self):
        if not self.responses:
            raise AssertionError("unexpected additional provider call")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)

def request(task, call_id="chat-call", **updates):
    values = dict(task_id=task.task_id, call_id=call_id,
                  profile_id=task.model_profile_id,
                  messages=[{"role": "user", "content": "Return a small JSON object."}],
                  timeout_seconds=10.0)
    values.update(updates)
    return ModelRequest(**values)

def test_optional_call_preserves_mandatory_model_quota(model_runtime, chat_response):
    task, ledger, _ = model_runtime
    transport = ControlledTransport(chat_response)
    client = chat_client(model_runtime, transport)
    for i in range(6):
        ledger.reserve(task.task_id, "model", "already-used-" + str(i), "sha256:" + "1" * 64)
    with pytest.raises(FactoryError) as error:
        asyncio.run(client.generate(request(task, remaining_required=2)))
    assert error.value.code == ErrorCode.BUDGET_EXHAUSTED and not transport.calls
    asyncio.run(client.generate(request(task, remaining_required=1)))
    assert len(transport.calls) == 1
    assert "remaining_required" not in transport.calls[0][1]

def chat_client(runtime, transport, **options):
    task, ledger, artifacts = runtime
    profile = LLMProfile(profile_id=task.model_profile_id, service_id="fixture-chat",
                         model="fixture-chat-model", mode="api")
    endpoint = ModelEndpoint(base_url="https://chat.example.test/v1",
                             api_key=SecretStr("fixture-provider-key"))
    return LLMClient(profile, endpoint, ledger, artifacts, transport=transport, **options)

def operations(ledger):
    with sqlite3.connect(ledger.path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT * FROM operations ORDER BY reserved_at, operation_id"
        )]

def run(awaitable):
    return asyncio.run(awaitable)

def test_chat_compatible_response_persisted_and_reused(model_runtime, chat_response):
    task, ledger, artifacts = model_runtime
    transport = ControlledTransport(chat_response)
    client = chat_client(model_runtime, transport)
    result = run(client.generate(request(task)))
    assert json.loads(result.text) == {"answer": "ready", "count": 2}
    assert result.actual_model == "fixture-chat-model"
    assert (result.input_tokens, result.output_tokens) == (12, 8)
    assert artifacts.read(result.response_ref)
    assert run(client.generate(request(task))) == result
    assert len(transport.calls) == 1
    rows = operations(ledger)
    assert len(rows) == 1 and rows[0]["status"] == "SUCCEEDED"
    assert json.loads(rows[0]["metadata"])["actual_model"] == result.actual_model
    assert transport.calls[0][1]["timeout"] <= 10.0

def test_reused_call_id_binds_full_request_hash(model_runtime, chat_response):
    task, _, _ = model_runtime
    transport = ControlledTransport(chat_response)
    client = chat_client(model_runtime, transport)
    run(client.generate(request(task)))
    with pytest.raises(FactoryError) as failure:
        run(client.generate(request(task, messages=[{"role": "user", "content": "changed"}])))
    assert failure.value.code == ErrorCode.INPUT_CONFLICT
    assert len(transport.calls) == 1

def test_restart_reuses_success_without_another_provider_request(model_runtime, chat_response):
    task, ledger, artifacts = model_runtime
    result = run(chat_client(model_runtime, ControlledTransport(chat_response)).generate(request(task)))
    reopened = MetricsStore(ledger.path, ledger.guard)
    transport = ControlledTransport()
    second = chat_client((task, reopened, artifacts), transport)
    assert run(second.generate(request(task))) == result
    assert transport.calls == []
    assert len(operations(reopened)) == 1

def test_missing_usage_is_unknown_in_response_and_ledger(model_runtime, chat_response):
    task, ledger, _ = model_runtime
    chat_response.pop("usage")
    result = run(chat_client(model_runtime, ControlledTransport(chat_response)).generate(request(task)))
    assert result.input_tokens is None and result.output_tokens is None
    metadata = json.loads(operations(ledger)[0]["metadata"])
    assert metadata["input_tokens"] is None and metadata["output_tokens"] is None

@pytest.mark.parametrize("updates", [
    {"messages": []},
    {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "tool", "content": "unregistered tool response"}]},
    {"timeout_seconds": 0.0},
    {"timeout_seconds": 61.0},
])
def test_invalid_generation_request_does_not_spend_budget(model_runtime, updates):
    task, ledger, _ = model_runtime
    transport = ControlledTransport()
    with pytest.raises(FactoryError):
        run(chat_client(model_runtime, transport).generate(request(task, **updates)))
    assert operations(ledger) == [] and transport.calls == []

@pytest.mark.parametrize("mutation", [
    lambda response: response.update(choices=[]),
    lambda response: response["choices"][0]["message"].update(content=None),
    lambda response: response["choices"][0].update(finish_reason="length"),
    lambda response: response.update(usage={"prompt_tokens": -1, "completion_tokens": 2}),
])
def test_invalid_chat_response_rejected(model_runtime, chat_response, mutation):
    task, ledger, _ = model_runtime
    mutation(chat_response)
    transport = ControlledTransport(chat_response)
    with pytest.raises(FactoryError) as failure:
        run(chat_client(model_runtime, transport).generate(request(task)))
    assert failure.value.code == ErrorCode.MODEL_OUTPUT_INVALID
    assert len(transport.calls) == 1
    assert operations(ledger)[0]["status"] == "FAILED"

class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    count: int

def test_structured_output_validated_before_success(model_runtime, chat_response):
    task, ledger, _ = model_runtime
    client = chat_client(model_runtime, ControlledTransport(chat_response))
    result = run(client.generate_structured(request(task), StructuredAnswer))
    assert result == StructuredAnswer(answer="ready", count=2)
    assert operations(ledger)[0]["status"] == "SUCCEEDED"

@pytest.mark.parametrize("text", [
    '{"answer":"ready","count":1,"count":2}',
    '```json\n{"answer":"ready","count":2}\n```',
    '{"answer":"ready","count":"2"}',
    '{"answer":"ready","count":NaN}',
    '{"answer":"ready"}',
])
def test_invalid_structured_text_is_failed_call(model_runtime, chat_response, text):
    task, ledger, _ = model_runtime
    chat_response["choices"][0]["message"]["content"] = text
    with pytest.raises(FactoryError) as failure:
        run(chat_client(model_runtime, ControlledTransport(chat_response)).generate_structured(
            request(task), StructuredAnswer))
    assert failure.value.code == ErrorCode.MODEL_OUTPUT_INVALID
    assert operations(ledger)[0]["status"] == "FAILED"

def test_structured_schema_changes_cannot_reuse_call_id(model_runtime, chat_response):
    task, _, _ = model_runtime
    client = chat_client(model_runtime, ControlledTransport(chat_response))
    run(client.generate_structured(request(task), StructuredAnswer))

    class OtherSchema(BaseModel):
        answer: str

    with pytest.raises(FactoryError) as failure:
        run(client.generate_structured(request(task), OtherSchema))
    assert failure.value.code == ErrorCode.INPUT_CONFLICT

def test_rate_limit_retry_consumes_distinct_budget_attempts(model_runtime, chat_response):
    task, ledger, _ = model_runtime
    error = ModelCallError(ErrorCode.MODEL_ERROR, "rate_limit", http_status=429, retryable=True)
    transport = ControlledTransport(error, chat_response)
    result = run(chat_client(model_runtime, transport, max_attempts=2).generate(request(task)))
    assert result.actual_model == "fixture-chat-model"
    rows = operations(ledger)
    assert len(rows) == 2 and len(transport.calls) == 2
    assert sorted(row["attempt"] for row in rows) == [1, 2]
    assert {row["status"] for row in rows} == {"FAILED", "SUCCEEDED"}

def test_authentication_failure_is_not_retried_and_repeated_failure_is_reused(model_runtime):
    task, ledger, _ = model_runtime
    error = ModelCallError(ErrorCode.MODEL_ERROR, "authentication", http_status=401)
    transport = ControlledTransport(error)
    client = chat_client(model_runtime, transport, max_attempts=3)
    for _ in range(2):
        with pytest.raises(ModelCallError) as failure:
            run(client.generate(request(task)))
        assert failure.value.http_status == 401
    assert len(transport.calls) == 1
    assert len(operations(ledger)) == 1

def test_timeout_unknown_is_never_automatically_repeated(model_runtime):
    task, ledger, _ = model_runtime
    transport = ControlledTransport(ModelCallError(
        ErrorCode.MODEL_TIMEOUT, "timeout", retryable=True, outcome_unknown=True))
    client = chat_client(model_runtime, transport, max_attempts=3)
    for _ in range(2):
        with pytest.raises(FactoryError) as failure:
            run(client.generate(request(task)))
        assert failure.value.code == ErrorCode.MODEL_TIMEOUT
    rows = operations(ledger)
    assert len(transport.calls) == len(rows) == 1
    assert rows[0]["status"] == "UNKNOWN"

def test_client_enforces_timeout_even_when_transport_ignores_it(model_runtime, chat_response):
    task, ledger, _ = model_runtime

    class SlowTransport(ControlledTransport):
        async def chat(self, **kwargs):
            self.calls.append(("chat", kwargs))
            await asyncio.sleep(0.3)
            return deepcopy(chat_response)

    transport = SlowTransport()
    with pytest.raises(FactoryError) as failure:
        run(chat_client(model_runtime, transport, max_attempts=3).generate(
            request(task, timeout_seconds=0.1)))
    assert failure.value.code == ErrorCode.MODEL_TIMEOUT
    assert operations(ledger)[0]["status"] == "UNKNOWN"
    assert len(transport.calls) == 1

def test_cancelled_call_becomes_unknown_without_automatic_resend(model_runtime):
    task, ledger, artifacts = model_runtime
    class CancelledTransport(ControlledTransport):
        async def chat(self, **kwargs):
            self.calls.append(("chat", kwargs))
            raise asyncio.CancelledError()

    transport = CancelledTransport()
    client = chat_client(model_runtime, transport, max_attempts=3)
    with pytest.raises(asyncio.CancelledError):
        run(client.generate(request(task)))
    assert operations(ledger)[0]["status"] == "UNKNOWN"
    reopened = MetricsStore(ledger.path, ledger.guard)
    with pytest.raises(FactoryError):
        run(chat_client((task, reopened, artifacts), transport).generate(request(task)))
    assert len(transport.calls) == 1 and len(operations(ledger)) == 1

def test_budget_exhaustion_prevents_extra_provider_call(model_runtime):
    task, ledger, _ = model_runtime
    error = ModelCallError(ErrorCode.MODEL_ERROR, "rate_limit", http_status=429, retryable=True)
    transport = ControlledTransport(*([error] * 9))
    client = chat_client(model_runtime, transport)
    for number in range(task.budgets.model_calls):
        with pytest.raises(ModelCallError):
            run(client.generate(request(task, call_id=f"attempt-{number}")))
    with pytest.raises(FactoryError) as failure:
        run(client.generate(request(task, call_id="over-budget")))
    assert failure.value.code == ErrorCode.BUDGET_EXHAUSTED
    assert len(transport.calls) == len(operations(ledger)) == task.budgets.model_calls

def test_profile_mismatch_rejected_before_reserving_budget(model_runtime):
    task, ledger, _ = model_runtime
    transport = ControlledTransport()
    with pytest.raises(FactoryError):
        run(chat_client(model_runtime, transport).generate(request(task, profile_id="wrong")))
    assert operations(ledger) == [] and transport.calls == []

def test_task_mode_mismatch_rejected_before_provider_request(model_runtime):
    task, ledger, artifacts = model_runtime
    mock_task = task.model_copy(update={"task_id": "mock-task", "model_mode": "mock"})
    ledger.create_task(mock_task)
    transport = ControlledTransport()
    with pytest.raises(FactoryError):
        run(chat_client((mock_task, ledger, artifacts), transport).generate(request(mock_task)))
    assert operations(ledger) == [] and transport.calls == []

def test_credential_content_is_not_persisted_or_rethrown(model_runtime, chat_response):
    task, ledger, artifacts = model_runtime
    chat_response["choices"][0]["message"]["content"] = "fixture-provider-key"
    with pytest.raises(FactoryError) as failure:
        run(chat_client(model_runtime, ControlledTransport(chat_response)).generate(request(task)))
    assert "fixture-provider-key" not in str(failure.value)
    for item in artifacts.root.iterdir():
        assert b"fixture-provider-key" not in item.read_bytes()
    assert b"fixture-provider-key" not in ledger.path.read_bytes()

@pytest.mark.parametrize("error", [
    RuntimeError("password=fixture-provider-key"),
    ModelCallError(ErrorCode.MODEL_ERROR, "password=fixture-provider-key"),
])
def test_transport_exception_content_is_not_persisted_or_rethrown(model_runtime, error):
    task, ledger, artifacts = model_runtime
    with pytest.raises(FactoryError) as failure:
        run(chat_client(model_runtime, ControlledTransport(error)).generate(request(task)))
    assert "fixture-provider-key" not in str(failure.value)
    for item in artifacts.root.iterdir():
        assert b"fixture-provider-key" not in item.read_bytes()
    assert b"fixture-provider-key" not in ledger.path.read_bytes()

def test_retry_wait_is_clipped_to_original_task_deadline(model_runtime, monkeypatch):
    task, ledger, artifacts = model_runtime
    now = [1000.0]
    ledger.clock = lambda: now[0]
    task = task.model_copy(update={"task_id": "short-deadline", "budgets": task.budgets.model_copy(update={"wall_seconds": 1})})
    ledger.create_task(task)
    waits = []

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(asyncio, "sleep", sleep)
    transport = ControlledTransport(ModelCallError(ErrorCode.MODEL_ERROR, "rate_limited", http_status=429, retryable=True))
    client = chat_client((task, ledger, artifacts), transport, max_attempts=2,
                         retry_delay_seconds=60, clock=lambda: now[0])
    with pytest.raises(ModelCallError) as failure:
        run(client.generate(request(task)))
    assert failure.value.code == ErrorCode.DEADLINE_EXCEEDED
    assert waits == [1.0]
    assert len(transport.calls) == len(operations(ledger)) == 1

def test_simultaneous_same_call_id_sends_once(model_runtime, chat_response):
    task, ledger, _ = model_runtime

    class BlockingTransport(ControlledTransport):
        async def chat(self, **kwargs):
            self.calls.append(("chat", kwargs))
            await asyncio.sleep(0.01)
            return deepcopy(chat_response)

    transport = BlockingTransport()
    client = chat_client(model_runtime, transport)

    async def invoke():
        return await asyncio.gather(client.generate(request(task)), client.generate(request(task)), return_exceptions=True)

    results = run(invoke())
    assert len(transport.calls) == 1
    assert sum(isinstance(result, ModelCallError) for result in results) == 1
    assert operations(ledger)[0]["status"] == "SUCCEEDED"

def test_other_registered_credential_rejected_before_artifact_publication(model_runtime, chat_response):
    from factory.runtime import SecretGuard

    task, ledger, artifacts = model_runtime
    ledger.guard = SecretGuard(("fixture-provider-key", "second-service-key"))
    chat_response["choices"][0]["message"]["content"] = "second-service-key"
    with pytest.raises(ModelCallError):
        run(chat_client(model_runtime, ControlledTransport(chat_response)).generate(request(task)))
    assert all(b"second-service-key" not in item.read_bytes() for item in artifacts.root.iterdir())
