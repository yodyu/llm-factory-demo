"""Read-only evidence projections, including missing and tampered artifacts."""
import json
from pathlib import Path
import shutil

import pytest

from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore
from factory.metrics.publication import publish
from factory.metrics.review import (
    conflicting_upper_terms, knowledge_usage, metric_text, publication_evidence,
    read_json, source_bytes,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def recorded_run(tmp_path):
    directory = tmp_path / "recorded"
    shutil.copytree(ROOT / "case-example/metrics/delivery/real-memory-v1", directory)
    report = read_json(directory, "report.json")
    store = KnowledgeStore(tmp_path / "knowledge.sqlite")
    receipt = publish(store, report)
    (directory / "publication.json").write_text(json.dumps(receipt))
    return directory, report, store


def test_publication_review_is_bound_and_read_only(recorded_run):
    directory, report, store = recorded_run
    before = store.path.read_bytes()
    evidence = publication_evidence(directory, report, store.path)
    assert evidence["receipt"]["status"] == "PUBLISHED" and not evidence["notes"]
    kinds = {n["kind"] for n in evidence["nodes"]}
    assert kinds == {"Implementation", "ValidationRun", "Experience"}
    experiences = [n["payload"] for n in evidence["nodes"] if n["kind"] == "Experience"]
    assert any(e["reusable_implementation"] for e in experiences)
    assert any(not e["implementation_verified"] for e in experiences)
    assert all(e["task_id"] == report["task"]["task_id"] for e in experiences)
    assert store.path.read_bytes() == before


def test_receipt_success_is_not_claimed_as_verified_when_db_is_unavailable(recorded_run, tmp_path):
    directory, report, _ = recorded_run
    missing = tmp_path / "must-not-create.sqlite"
    result = publication_evidence(directory, report, missing)
    assert result["receipt"]["status"] == "PUBLISHED" and result["notes"] and not result["nodes"]
    assert not missing.exists()


def test_wrong_receipt_or_changed_knowledge_node_is_rejected(recorded_run):
    directory, report, store = recorded_run
    receipt = read_json(directory, "publication.json")
    (directory / "publication.json").write_text(json.dumps({**receipt, "publication_id": "other-report"}))
    with pytest.raises(ValueError, match="不绑定"):
        publication_evidence(directory, report, store.path)
    (directory / "publication.json").write_text(json.dumps(receipt))
    with store.transaction() as db:
        db.execute("UPDATE nodes SET payload='{}' WHERE id=?", (receipt["node_ids"][0],))
    with pytest.raises(ValueError, match="摘要不匹配"):
        publication_evidence(directory, report, store.path)


def test_missing_and_pending_publication_do_not_create_a_store(recorded_run, tmp_path):
    directory, report, _ = recorded_run
    path = directory / "publication.json"
    path.unlink()
    assert publication_evidence(directory, report, tmp_path / "missing.sqlite")["receipt"]["status"] == "NOT_RECORDED"
    path.write_text(json.dumps({"status": "PENDING_RETRY", "failure": {"code": "controlled-storage-error"}}))
    assert publication_evidence(directory, report, tmp_path / "missing.sqlite")["receipt"]["failure"]["code"] == "controlled-storage-error"
    assert not (tmp_path / "missing.sqlite").exists()


def test_source_download_checks_digest_and_path_scope(recorded_run, tmp_path):
    directory, report, _ = recorded_run
    version = report["candidates"][0]["versions"][-1]
    assert source_bytes(directory, version)
    path = directory / version["source_path"]
    path.write_text(path.read_text() + "\n# changed")
    with pytest.raises(ValueError, match="源码摘要"):
        source_bytes(directory, version)
    with pytest.raises(ValueError):
        source_bytes(directory, {**version, "source_path": "../outside.py"})
    outside = tmp_path / "outside.py"
    outside.write_text("private bytes")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="path leaves"):
        source_bytes(directory, version)


def test_supplied_and_explicitly_cited_knowledge_and_experiences_are_distinct():
    report = {"retrieval": {"knowledge_ids": ["cap", "chunk", "experience"], "experiences": [{"id": "experience"}]},
              "candidates": [{"candidate_id": "fixed", "plan": {"knowledge_ids": ["cap"]},
                              "versions": [{"version": 0, "knowledge_ids": ["chunk"]}]}]}
    usage = knowledge_usage(report)
    assert usage["supplied_experiences"] == ["experience"] and not usage["cited_experiences"]
    assert usage["cited"] == ["cap", "chunk"]
    report["candidates"][0]["versions"][0]["knowledge_ids"] = ["experience", "invented"]
    assert knowledge_usage(report)["cited_experiences"] == ["experience"]
    assert knowledge_usage(report)["unprovided_citations"] == ["invented"]


def test_undefined_metrics_keep_reason_while_real_zero_is_zero():
    assert metric_text({"value": None, "null_reason": "no_predictions"}) == "未定义（no_predictions）"
    assert metric_text(None) == "未记录（not_recorded）"
    assert metric_text({"value": 0.0}, percent=True) == "0.0%"
    assert metric_text({"value": 1.0}, percent=True) == "100.0%"


@pytest.mark.parametrize("text", ["检测持续下降", "检测内存利用率下降", "低于 15 时告警", "使用下界", "双侧异常检测", "target lower"])
def test_explicit_text_conflicts_are_flagged_for_upper_page(text):
    assert conflicting_upper_terms(text)


@pytest.mark.parametrize("text", ["检测持续升高", "不检测下降，仅检测升高", "不采用 lower", "正常业务波动"])
def test_upper_or_explicitly_negated_words_are_not_flagged(text):
    assert not conflicting_upper_terms(text)
