from factory.metrics.experiment import summary
from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore, sources_only, verify_snapshot


def test_failed_planning_stays_in_experiment_candidate_and_task_denominators():
    failed = {"task": {"task_id": "failed"}, "status": "FAILED", "candidates": [], "failure": {"code": "MODEL_ERROR"}}
    passed = {"task": {"task_id": "passed"}, "status": "COMPLETED", "final": {"engineering_status": "PASSED"},
              "candidates": [{"versions": [{"validation": {"passed": True}}], "report": {"engineering_status": "PASSED"}},
                             {"versions": [{"validation": {"passed": False}}, {"validation": {"passed": False}}],
                              "report": {"engineering_status": "FAILED"}}]}
    records = [{"condition": "none", "scenario": "test", "report": report, "directory": "test"} for report in (failed, passed)]
    value = summary(records, {"conditions": ["none", "structured"], "protocol": "test", "interpretation": "exploratory"})
    arm = value["arms"]["none"]
    assert arm["attempted_tasks"] == 2 and arm["task_success_rate"] == 0.5
    assert arm["expected_candidates"] == 4 and arm["first_pass_rate"] == 0.25
    assert arm["code_repairs"] == 1 and value["arms"]["structured"]["task_success_rate"] is None


def test_study_snapshot_removes_all_run_experience_and_its_edges(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite")
    store.add([{"id": "cap", "kind": "Capability", "payload": {}},
               {"id": "impl", "kind": "Implementation", "payload": {}},
               {"id": "exp", "kind": "Experience", "payload": {}}],
              [{"source": "cap", "relation": "IMPLEMENTED_BY", "target": "impl", "provenance": {}}])
    value = sources_only(store.snapshot())
    verify_snapshot(value)
    assert [node["kind"] for node in value["nodes"]] == ["Capability"] and value["relations"] == []


def test_focused_first_response_experiment_uses_fixed_plans_and_no_repairs(tmp_path):
    import os
    from pathlib import Path
    import asyncio
    import pytest
    from types import SimpleNamespace
    from factory.metrics.focused_experiment import focused
    from factory.metrics.synthetic import generate, write_dataset
    from factory.metrics.workflow import write_json
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    data = tmp_path / "data"
    write_dataset(data, generate("disk_peaks"))
    snapshot = tmp_path / "snapshot.json"
    write_json(snapshot, KnowledgeStore(tmp_path / "knowledge.sqlite").snapshot())
    task = tmp_path / "task.json"
    write_json(task, {"requirement": "检测磁盘延迟升高", "explicit_constraints": {"threshold": 40.0, "direction": "upper"}})
    config = os.environ.get("FACTORY_NEO4J_CONFIG", os.environ.get("METRICS_NEO4J_CONFIG"))
    if not config:
        pytest.skip("需要设置 FACTORY_NEO4J_CONFIG 以运行实验集成测试")
    args = SimpleNamespace(knowledge=Path(config), snapshot=snapshot, dataset=data, task=task, state=tmp_path / "state", mode="mock", campaign=None,
                           env_file=None, output=tmp_path / "experiment", image=image, prefix="test-focused")
    result = asyncio.run(focused(args))
    assert result["model_requests_planned"] == 4 and result["campaign_budget"] is None
    assert [arm["attempts"] for arm in result["arms"]] == [2, 2]
    assert [arm["first_response_passed"] for arm in result["arms"]] == [2, 2]
