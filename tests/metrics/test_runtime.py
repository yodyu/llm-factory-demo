import sqlite3

import pytest

from contracts import FactoryError
from contracts.metrics import MetricsBudgets, MetricsTask
from factory.metrics.runtime import MetricsStore
from factory.runtime.artifacts import digest


def task(**changes):
    fields = dict(task_id="metrics-1", requirement="检测单指标持续升高", dataset_id="demo", metric="cpu",
                  anomaly_target="upper", explicit_constraints={}, ranking_preferences=[],
                  allowed_methods=["fixed_threshold", "rolling_mad"], knowledge_snapshot=digest(b"{}"),
                  model_mode="mock", model_profile_id="metrics-mock")
    fields.update(changes)
    return MetricsTask(**fields)


def test_numeric_registration_reuses_reservations_without_ops_scenario(tmp_path):
    store = MetricsStore(tmp_path / "metrics.sqlite")
    spec = task(budgets=MetricsBudgets(model_calls=1))
    row = store.create_task(spec)
    assert row["job_kind"] == "metrics_factory" and row["lifecycle_version"] == "metrics-task/1"
    assert store.create_task(spec)["deadline"] == row["deadline"]
    assert store.model_context(spec.task_id)["binding_hash"] == row["spec_hash"]
    reservation = store.reserve(spec.task_id, "model", "call-1", digest(b"call"))
    assert reservation["is_new"]
    assert not store.reserve(spec.task_id, "model", "call-1", digest(b"call"))["is_new"]
    with pytest.raises(FactoryError, match="budget"):
        store.reserve(spec.task_id, "model", "call-2", digest(b"call"))
    with pytest.raises(FactoryError, match="immutable"):
        store.create_task(task(requirement="changed"))
    with pytest.raises(TypeError):
        store.create_task({})


def test_adapter_refuses_to_migrate_existing_database(tmp_path):
    path = tmp_path / "other.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sentinel(value TEXT)")
        db.execute("INSERT INTO sentinel VALUES ('untouched')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="non-metrics"):
        MetricsStore(path)
    assert path.read_bytes() == before


def test_selection_freezes_model_calls_and_phase_evidence(tmp_path):
    store = MetricsStore(tmp_path / "metrics.sqlite")
    store.create_task(task())
    with pytest.raises(ValueError, match="transition"):
        store.phase("metrics-1", "SELECTED", {})
    for phase in ("DATA_READY", "KNOWLEDGE_READY", "PLANNED", "VALIDATING", "SELECTED"):
        store.phase("metrics-1", phase, {"phase": phase})
    assert store.phase("metrics-1", "SELECTED", {"phase": "SELECTED"})
    with pytest.raises(FactoryError):
        store.phase("metrics-1", "SELECTED", {"different": True})
    with pytest.raises(FactoryError, match="forbidden"):
        store.reserve("metrics-1", "model", "forbidden", digest(b""))
    with pytest.raises(FactoryError, match="forbidden"):
        store.reserve("metrics-1", "repair", "forbidden-repair", digest(b""))
    # Final evaluation can reserve code, but can never return to repair/generation.
    assert store.reserve("metrics-1", "metrics-code", "final", digest(b"frozen"))["is_new"]
    store.phase("metrics-1", "FINAL_EVALUATED", {"effect_status": "MEASURED"})
    store.phase("metrics-1", "COMPLETED", {"acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD"})
    assert store.task("metrics-1")["status"] == "SUCCEEDED"
    with pytest.raises(ValueError, match="terminal"):
        store.reserve("metrics-1", "metrics-code", "again", digest(b"x"))
