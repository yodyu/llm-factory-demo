"""Controlled transports and numeric ledger; no real API requests."""
import json
from pathlib import Path
import pytest
from contracts.metrics import MetricsBudgets
from factory.metrics.runtime import MetricsStore
from factory.runtime import SecretGuard
from tests.metrics.test_runtime import task as numeric_task

@pytest.fixture
def model_runtime(tmp_path):
    task = numeric_task(model_mode="api", model_profile_id="fixture-chat", budgets=MetricsBudgets(model_calls=8))
    ledger = MetricsStore(tmp_path / "factory.db", SecretGuard(("fixture-provider-key",)))
    ledger.create_task(task)
    return task, ledger, ledger.artifact_store

@pytest.fixture
def chat_response():
    return json.loads((Path(__file__).parent / "fixtures/chat.json").read_bytes())
