import asyncio
import json
import os
import zipfile

import pytest

from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore, retrieve
from factory.metrics.model import make_gateway
from factory.metrics.publication import publish
from factory.metrics.reports import export_run
from factory.metrics.runtime import MetricsStore
from factory.metrics.synthetic import generate, write_dataset
from factory.metrics.workflow import run


@pytest.fixture
def setup_run(tmp_path):
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    state = tmp_path / "state"
    store = MetricsStore(state / "runtime.sqlite")
    gateway = make_gateway(store, mode="mock")
    data = tmp_path / "dataset"
    write_dataset(data, generate("memory_shift"))
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    request = {"requirement": "检测内存持续升高，阈值85上界，连续两点", "anomaly_target": "upper",
               "explicit_constraints": {"threshold": 85.0, "direction": "upper", "persistence_points": 2.0}}
    return state, store, gateway, data, knowledge, image, request


def launch(setup, **kwargs):
    state, store, gateway, data, knowledge, image, request = setup
    return asyncio.run(run(store, gateway, state=state, task_input=request, dataset_root=data,
                           snapshot=knowledge.snapshot(), knowledge=knowledge, image=image, **kwargs))


def test_mock_full_workflow_freezes_test_publishes_and_exports(setup_run, tmp_path):
    result = launch(setup_run)
    state, store, _, data, knowledge, _, _ = setup_run
    from pathlib import Path
    directory = Path(result["directory"])
    report = json.loads((directory / "report.json").read_text())
    assert report["status"] == "COMPLETED", report.get("failure")
    assert report["origin"] == "mock" and report["final_test_executed"]
    assert len(report["candidates"]) == 2
    assert report["final"]["acceptance_status"] == "MEASURED_NO_ACCEPTANCE_THRESHOLD"
    assert result["publication"]["status"] == "PUBLISHED"
    assert store.task(result["task_id"])["phase"] == "COMPLETED"
    with store._transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM operations WHERE operation_id LIKE '%:final-test'").fetchone()[0] == 1
        prompts = [store.document(row[0]) for row in db.execute("SELECT reference FROM task_artifacts WHERE role='model-prompt'")]
    for prompt in prompts:
        text = json.dumps(prompt, ensure_ascii=False)
        assert '"test.csv"' not in text and "injection_intervals" not in text and "labels_sha256" not in text
    count = len(knowledge.snapshot()["nodes"])
    assert publish(knowledge, report) == result["publication"]
    assert len(knowledge.snapshot()["nodes"]) == count
    found = retrieve(knowledge.snapshot(), requirement="内存", metric_kind="gauge",
                     allowed_methods=["fixed_threshold", "rolling_mad"], history_points=60, origin="mock")
    assert found["experiences"]
    assert all("final" not in experience or not isinstance(experience["final"], dict) for experience in found["experiences"])
    output = tmp_path / "bundle.zip"
    exported = export_run(store, directory, output, dataset_root=data)
    assert exported["files"] > 10
    with zipfile.ZipFile(output) as archive:
        assert "operations.json" in archive.namelist() and "bundle-manifest.json" in archive.namelist()
        assert not any(name.endswith((".sqlite", ".env")) for name in archive.namelist())
    from factory.metrics.replay import replay_bundle
    replay = replay_bundle(output, exported["sha256"], state=tmp_path / "replay", image=setup_run[5])
    assert replay["model_calls"] == 0 and replay["origin"] == "historical"
    assert replay["status"] == "COMPLETED" and replay["effect_matches_recorded"] is True
    with pytest.raises(ValueError, match="archive digest"):
        replay_bundle(output, "sha256:" + "0" * 64, state=tmp_path / "tampered-replay", image=setup_run[5])
    from factory.metrics.requalification import requalify
    qualified = requalify(store, directory, data, state=tmp_path / "qualified", image=setup_run[5], knowledge=knowledge)
    assert qualified["status"] == "COMPLETED" and qualified["model_calls"] == 0
    assert qualified["prior_test_exposure"] is True


def test_lower_workflow_without_redundant_direction_preserves_trusted_target(setup_run):
    from pathlib import Path
    setup_run[-1].update({"requirement": "检测内存下降；此数据仅验证执行方向，不宣称业务效果", "anomaly_target": "lower",
                          "explicit_constraints": {"threshold": 15.0}})
    result = launch(setup_run)
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert result["status"] == "COMPLETED", report.get("failure")
    assert report["planning"]["anomaly_target"] == "lower"
    assert all(c["plan"]["config"]["direction"] == "lower" and c["versions"][0]["validation"]["passed"] for c in report["candidates"])
    assert report["final_test_executed"] and report["final"]["acceptance_status"] == "MEASURED_NO_ACCEPTANCE_THRESHOLD"


def test_source_tampering_rejected_before_final_read(setup_run, monkeypatch):
    import factory.metrics.workflow as workflow
    original = workflow.final_evaluate
    test_reads = []
    loader = workflow.load_role

    def checked_load(root, manifest, role):
        if role == "test":
            test_reads.append(role)
        return loader(root, manifest, role)

    def tamper(store, runner, task_id, root, directory):
        frozen = json.loads((directory / "selection.json").read_text())
        with (directory / frozen["source_path"]).open("a") as stream:
            stream.write("\n# tampered after method validation\n")
        return original(store, runner, task_id, root, directory)

    monkeypatch.setattr(workflow, "load_role", checked_load)
    monkeypatch.setattr(workflow, "final_evaluate", tamper)
    result = launch(setup_run)
    from pathlib import Path
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert report["status"] == "FAILED" and report["failure"]["code"] == "DATA_HASH_MISMATCH"
    assert test_reads == [] and not report["final_test_executed"]
    assert len(report["model_operations"]) == 3


def test_failed_candidates_stop_after_two_repairs_and_keep_failure_experience(setup_run, monkeypatch):
    from factory.metrics.mock import MockTransport
    original = MockTransport.chat

    async def broken(self, **kwargs):
        answer = await original(self, **kwargs)
        stage = json.loads(kwargs["messages"][1]["content"])["stage"]
        if stage.startswith("code-"):
            value = json.loads(answer["choices"][0]["message"]["content"])
            value["source"] = "def create_detector(config):\n    raise ValueError('controlled failure')\n"
            answer["choices"][0]["message"]["content"] = json.dumps(value)
        return answer

    monkeypatch.setattr(MockTransport, "chat", broken)
    result = launch(setup_run)
    from pathlib import Path
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert report["status"] == "FAILED" and not report["final_test_executed"]
    assert [len(candidate["versions"]) for candidate in report["candidates"]] == [3, 3]
    _, store, _, _, knowledge, _, _ = setup_run
    with store._transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM operations WHERE resource='repair'").fetchone()[0] == 4
    experiences = [n["payload"] for n in knowledge.snapshot()["nodes"] if n["kind"] == "Experience"]
    assert len(experiences) == 6 and all(not e["reusable_implementation"] for e in experiences)


def test_final_failure_does_not_generate_repair_or_select_second(setup_run, monkeypatch):
    import factory.metrics.workflow as workflow
    loader = workflow.load_role

    def final_fails(root, manifest, role):
        if role == "test":
            raise ValueError("controlled final input failure")
        return loader(root, manifest, role)

    monkeypatch.setattr(workflow, "load_role", final_fails)
    result = launch(setup_run)
    from pathlib import Path
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert report["status"] == "FAILED" and report["final"]["execution_status"] == "FAILED"
    assert report["final"]["selected"] == report["selection"]["selected"]
    assert len(report["model_operations"]) == 3
    assert not report["final_test_executed"]


def test_interrupted_model_call_is_terminal_and_never_retried(setup_run, monkeypatch):
    from factory.metrics.mock import MockTransport

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(MockTransport, "chat", cancelled)
    with pytest.raises(asyncio.CancelledError):
        launch(setup_run, task_id="interrupted")
    state, store, *_ = setup_run
    reports = list(state.glob("runs/*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["status"] == "FAILED" and report["failure"]["code"] == "INTERRUPTED"
    assert store.task("interrupted")["phase"] == "FAILED"
    with store._transaction() as db:
        rows = db.execute("SELECT status FROM operations WHERE resource='model'").fetchall()
    assert [row[0] for row in rows] == ["UNKNOWN"]
