"""Graph routing, side-effect boundaries and evidence compatibility."""

import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from contracts import ErrorCode, FactoryError
from factory.metrics.orchestration.candidate import build_candidate_graph
from factory.metrics.orchestration.graph import build_task_graph
from factory.metrics.reports import export_run
from tests.metrics import test_workflow
from tests.metrics.test_workflow import launch

setup_run = test_workflow.setup_run


def reachable(graph, source):
    pending, seen = [source], set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(edge.target for edge in graph.edges if edge.source == node)
    return seen


def test_final_boundary_cannot_reach_model_or_candidate_nodes():
    graph = build_task_graph(None).get_graph()
    assert {"freeze_selection", "final_evaluate", "write_report", "publish", "export"} <= set(graph.nodes)
    for name in ("freeze_selection", "final_evaluate", "resolve_outcome"):
        assert not reachable(graph, name) & {"plan_candidates", "run_candidate", "next_candidate", "select_candidate"}
    candidate = build_candidate_graph(None).get_graph()
    assert "generate_version" in reachable(candidate, "reserve_repair")
    assert "generate_version" not in reachable(candidate, "calibrate_candidate")


def test_repair_is_executed_by_graph_and_evidence_is_digest_bound(setup_run, tmp_path):
    result = launch(setup_run, fault_injection=True)
    directory = Path(result["directory"])
    report = json.loads((directory / "report.json").read_text())
    evidence = json.loads((directory / "orchestration.json").read_text())
    assert report["status"] == "COMPLETED"
    assert report["orchestration"]["engine"] == "langgraph"
    events = [e for e in evidence["events"] if e["event"] == "finished"]
    repairs = [e for e in events if e["node"] == "reserve_repair"]
    assert repairs and all(1 <= e["version"] <= 2 for e in repairs)
    for repair in repairs:
        version_events = [e["node"] for e in events if e.get("candidate_id") == repair["candidate_id"]
                          and e.get("version") == repair["version"]]
        assert version_events.index("reserve_repair") < version_events.index("generate_version") < version_events.index("validate_version")
    assert {"node", "event", "at_seconds", "candidate_id", "version", "code"} >= set().union(*(set(e) for e in evidence["events"]))
    output = tmp_path / "new-graph.zip"
    exported = export_run(setup_run[1], directory, output, dataset_root=setup_run[3])
    assert exported["files"] > 10
    with zipfile.ZipFile(output) as archive:
        assert "orchestration.json" in archive.namelist()
    (directory / "orchestration.json").write_text("{}")
    with pytest.raises(ValueError, match="orchestration"):
        export_run(setup_run[1], directory, tmp_path / "tampered.zip", dataset_root=setup_run[3])


def test_fatal_candidate_budget_stops_next_candidate(setup_run, monkeypatch):
    import factory.metrics.workflow as workflow
    called = []

    async def exhausted(*args, **kwargs):
        called.append(1)
        raise FactoryError(ErrorCode.BUDGET_EXHAUSTED, "controlled model budget exhaustion")

    monkeypatch.setattr(workflow, "generate", exhausted)
    result = launch(setup_run)
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert called == [1]
    assert report["status"] == "BUDGET_EXHAUSTED" and not report["final_test_executed"]
    assert len(report["candidates"]) == 1 and result["status"] == "PLAN_ONLY"
    assert setup_run[1].task(result["task_id"])["phase"] == "BUDGET_EXHAUSTED"


def test_publish_failure_still_exports_frozen_report(setup_run, monkeypatch):
    def unavailable(*args):
        raise ValueError("controlled graph publication failure")

    monkeypatch.setattr("factory.metrics.publication.publish_pending", unavailable)
    result = launch(setup_run, export_delivery=True)
    directory = Path(result["directory"])
    assert result["workflow_status"] == "COMPLETED"
    assert result["publication"]["status"] == "PENDING_RETRY"
    assert (directory / "delivery.zip").exists()
    assert json.loads((directory / "export.json").read_text())["status"] == "SUCCEEDED"


def test_cleanup_failure_preserves_business_failure_and_report(setup_run, monkeypatch):
    async def invalid(*args, **kwargs):
        raise ValueError("controlled generation failure")

    def cleanup_failure(*args):
        raise ValueError("controlled cleanup failure")

    monkeypatch.setattr("factory.metrics.workflow.generate", invalid)
    monkeypatch.setattr("execution.metrics_runner.MetricsRunner.cleanup_orphans", cleanup_failure)
    result = launch(setup_run)
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert report["status"] == "FAILED"
    assert report["failure"]["message"] != report["cleanup_failure"]["message"]
    assert len(report["candidates"]) == 2


def test_export_failure_does_not_rewrite_business_report(setup_run, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("controlled export failure")

    monkeypatch.setattr("factory.metrics.reports.export_run", unavailable)
    with pytest.raises(RuntimeError, match="delivery export failed"):
        launch(setup_run, export_delivery=True)
    directory = next(setup_run[0].glob("runs/*"))
    report = json.loads((directory / "report.json").read_text())
    assert report["status"] == "COMPLETED"
    assert json.loads((directory / "export.json").read_text())["status"] == "FAILED"


def test_cancellation_records_partial_candidate_and_finalizes_once(setup_run, monkeypatch):
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr("factory.metrics.workflow.generate", cancelled)
    with pytest.raises(asyncio.CancelledError):
        launch(setup_run)
    directory = next(setup_run[0].glob("runs/*"))
    report = json.loads((directory / "report.json").read_text())
    assert report["failure"]["code"] == "INTERRUPTED"
    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["failure"]["code"] == "INTERRUPTED"
    with setup_run[1]._transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM task_artifacts WHERE role='run-report'").fetchone()[0] == 1


def test_cancellation_after_business_commit_preserves_ledger_outcome(setup_run, monkeypatch):
    from factory.metrics.orchestration import graph

    def cancelled_before_cleanup(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(graph, "cleanup", cancelled_before_cleanup)
    with pytest.raises(asyncio.CancelledError):
        launch(setup_run)
    directory = next(setup_run[0].glob("runs/*"))
    report = json.loads((directory / "report.json").read_text())
    assert report["status"] == "COMPLETED" and report["final_test_executed"]
    assert report["finalization_failure"]["code"] == "INTERRUPTED"
    assert setup_run[1].task(report["task"]["task_id"])["phase"] == "COMPLETED"
    assert len(report["model_operations"]) == 3
