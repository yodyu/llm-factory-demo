import asyncio
import copy

import pytest

from contracts import FactoryError
from contracts.metrics_knowledge import Extraction
from factory.metrics.budget import CallBudget
from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore, checked_extraction, import_material, ingest, retrieve, verify_snapshot
from factory.metrics.model import make_gateway
from factory.metrics.runtime import MetricsStore
from tests.metrics.test_runtime import task


def test_campaign_is_shared_persistent_and_conservative(tmp_path):
    path = tmp_path / "campaign.sqlite"
    budget = CallBudget(path, limit=2)
    first = MetricsStore(tmp_path / "one.sqlite", campaign=budget)
    second = MetricsStore(tmp_path / "two.sqlite", campaign=CallBudget(path, limit=2))
    for store in (first, second):
        store.create_task(task())
    first.reserve("metrics-1", "model", "one", "sha256:" + "a" * 64)
    first.mark_operation("one", "SENT")
    first.mark_operation("one", "UNKNOWN")
    second.reserve("metrics-1", "model", "two", "sha256:" + "b" * 64)
    assert not second.reserve("metrics-1", "model", "two", "sha256:" + "b" * 64)["is_new"]
    with pytest.raises(FactoryError, match="cap reached"):
        second.reserve("metrics-1", "model", "three", "sha256:" + "c" * 64)
    assert budget.summary()["reserved"] == 2 and budget.summary()["sent"] == 1
    with pytest.raises(ValueError, match="immutable"):
        CallBudget(path, limit=3)


def extracted(source, chunks, **overrides):
    value = {"local_id": "cap", "name": "test", "method_id": "rolling_mad", "summary": "MAD",
             "metric_kinds": ["gauge"], "single_host": True, "min_history": 15,
             "dependency_profile": "metrics-py312-stdlib/1", "conditions_status": "evidenced",
             "constraints": ["needs history"], "limitations": [],
             "citations": [{"chunk_id": chunks[0]["id"], "quote": chunks[0]["payload"]["text"].splitlines()[0], "symbol": None}]}
    value.update(overrides)
    return Extraction.model_validate({"capabilities": [value]})


def test_new_markdown_and_python_extract_again_without_execution(tmp_path):
    (tmp_path / "new.md").write_text("新材料：MAD 需要15点真实历史。\n")
    (tmp_path / "new.py").write_text('raise RuntimeError("MUST NOT EXECUTE")\ndef new_detector(x):\n    """MAD reference"""\n    return x\n')
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    for name in ("new.md", "new.py"):
        source, chunks = import_material(tmp_path, name)
        nodes, relations = checked_extraction(source, chunks, extracted(source, chunks), origin="llm_api", response_evidence={"request": "test"})
        knowledge.add(nodes, relations)
    snapshot = knowledge.snapshot()
    assert len([n for n in snapshot["nodes"] if n["kind"] == "Source"]) == 2
    assert {n["kind"] for n in snapshot["nodes"]} >= {"Source", "Chunk", "Capability", "Constraint"}
    assert all(not n["payload"]["implementation_verified"] for n in snapshot["nodes"] if n["kind"] == "Capability")
    assert all(r["source"] in {n["id"] for n in snapshot["nodes"]} for r in snapshot["relations"])
    old = snapshot["snapshot_id"]
    (tmp_path / "new.md").write_text("修改后的新材料\n")
    source, chunks = import_material(tmp_path, "new.md")
    knowledge.add(*checked_extraction(source, chunks, extracted(source, chunks), origin="llm_api", response_evidence={}))
    assert knowledge.snapshot()["snapshot_id"] != old


def test_bad_quote_and_nonexistent_code_symbol_are_rejected(tmp_path):
    (tmp_path / "a.py").write_text("def example():\n    return 1\n")
    source, chunks = import_material(tmp_path, "a.py")
    for quote, symbol in [("made up", None), ("def example():", "not_present")]:
        value = extracted(source, chunks, citations=[{"chunk_id": chunks[0]["id"], "quote": quote, "symbol": symbol}])
        with pytest.raises(ValueError):
            checked_extraction(source, chunks, value, origin="llm_api", response_evidence={})

    with pytest.raises(ValueError, match='UNSUPPORTED_IMPLEMENTATION_CLAIM'):
        checked_extraction(source, chunks, extracted(source, chunks, verification_level='reference_verified'),
                           origin='llm_api', response_evidence={})


def test_qualified_python_method_citation_is_a_real_ast_symbol(tmp_path):
    (tmp_path / "a.py").write_text("class Detector:\n    def fit(self, points):\n        return None\n")
    source, chunks = import_material(tmp_path, "a.py")
    value = extracted(source, chunks, citations=[{"chunk_id": chunks[0]["id"], "quote": "def fit(self, points):", "symbol": "Detector.fit"}])
    assert checked_extraction(source, chunks, value, origin="llm_api", response_evidence={})


def test_conditional_retrieval_and_snapshot_tampering(tmp_path):
    (tmp_path / "a.md").write_text("MAD requires past data\n")
    source, chunks = import_material(tmp_path, "a.md")
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    knowledge.add(*checked_extraction(source, chunks, extracted(source, chunks), origin="llm_api", response_evidence={}))
    snapshot = knowledge.snapshot()
    result = retrieve(snapshot, requirement="内存持续偏移", metric_kind="gauge", allowed_methods=["rolling_mad"], history_points=5)
    assert not result["chunks"] and result["excluded"][0]["reason"] == "insufficient_history"
    result = retrieve(snapshot, requirement="内存", metric_kind="rate", allowed_methods=["rolling_mad"], history_points=30)
    assert result["excluded"][0]["reason"] == "metric_kind_not_supported"
    good = retrieve(snapshot, requirement="内存", metric_kind="gauge", allowed_methods=["rolling_mad"], history_points=30)
    assert good["knowledge_ids"] and len(good["chunks"]) <= 6
    changed = copy.deepcopy(snapshot)
    changed["nodes"][0]["payload"]["tampered"] = True
    with pytest.raises(ValueError, match="digest"):
        verify_snapshot(changed)


def test_mock_ingest_uses_new_material_and_records_raw_model_outputs(tmp_path):
    (tmp_path / "a.md").write_text("新材料：单主机 gauge\n")
    runtime = MetricsStore(tmp_path / "runtime.sqlite")
    gateway = make_gateway(runtime, mode="mock")
    runtime.create_task(task(model_profile_id=gateway.client.profile.profile_id))
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    result = asyncio.run(ingest(tmp_path, ["a.md"], knowledge, gateway, "metrics-1", origin="mock"))
    assert result["origin"] == "mock" and result["sources"][0]["status"] == "source_checked"
    with runtime._transaction() as db:
        operation = db.execute("SELECT * FROM operations WHERE resource='model'").fetchone()
        assert operation["status"] == "SUCCEEDED"
        assert "controlled" in runtime.artifact_store.read(operation["result_ref"]).decode()


def test_plain_text_material_retains_source_bytes_and_line_citations(tmp_path):
    text = "单主机 gauge；MAD 需要真实历史。\n历史不足不得默认为正常。\n"
    (tmp_path / "new.txt").write_text(text)
    source, chunks = import_material(tmp_path, "new.txt")
    assert source["payload"]["material_type"] == "txt"
    assert chunks[0]["payload"]["start_line"] == 1
    assert chunks[0]["payload"]["end_line"] == 2
    assert chunks[0]["payload"]["text"] == text.rstrip("\n")
    assert checked_extraction(source, chunks, extracted(source, chunks), origin="mock", response_evidence={})
