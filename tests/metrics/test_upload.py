import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory.metrics.data import encode_csv
from contracts.metrics import MetricPoint
from factory.metrics.upload import inspect_upload, prepare_legacy_upload as prepare_upload, label_flags, UNKNOWN


def observations(delta=0):
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [MetricPoint(timestamp=start+timedelta(minutes=i), host_id="customer-host-7",
                        value=None if i in {230, 231, 232, 233} else float(91+delta if 250 <= i < 270 else 40+delta)) for i in range(360)]


def options():
    return dict(display_name="../../customer.csv", host_id="customer-host-7", metric="memory_utilization", unit="percent",
                metric_kind="gauge", sampling_seconds=60, valid_range=(0., 100.), fit_points=60, history_points=200,
                method="fixed_threshold")


def labels(points):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["timestamp", "host_id", "is_anomaly"])
    for p in points:
        writer.writerow([p.timestamp.isoformat(), p.host_id, int(p.value is not None and p.value > 85)])
    return out.getvalue().encode()


def test_preparation_binds_raw_values_and_never_uses_display_name_as_path(tmp_path):
    a = prepare_upload(tmp_path / "a", encode_csv(observations()), **options())
    b = prepare_upload(tmp_path / "b", encode_csv(observations(1)), **options())
    assert a["sha256"] != b["sha256"] and a["display_name"] == "customer.csv"
    assert json.loads((tmp_path / "a/manifest.json").read_text())["dataset_id"] != json.loads((tmp_path / "b/manifest.json").read_text())["dataset_id"]
    assert a["labels"] is None and a["splits"][2]["points"] == 160
    assert a["benchmark"]["status"] == "READY"
    assert not (tmp_path / "customer.csv").exists()


@pytest.mark.parametrize("change,match", [
    ({"unit": "seconds"}, "supported units"), ({"metric_kind": "counter"}, "counter"),
    ({"method": "rolling_mad", "history_points": 100}, "at least 60"),
    ({"history_points": 360}, "require"), ({"valid_range": (0, 30)}, "invalid timestamp")])
def test_input_errors_are_explicit(change, match):
    with pytest.raises(ValueError, match=match):
        inspect_upload(encode_csv(observations()), **{**options(), **change})


@pytest.mark.parametrize("mutation", ["duplicate", "unordered", "nan", "mixed_host", "extra_field"])
def test_bad_csv_rejected(mutation):
    lines = encode_csv(observations()).decode().splitlines()
    if mutation == "duplicate":
        lines[2] = lines[1]
    if mutation == "unordered":
        lines[2], lines[3] = lines[3], lines[2]
    if mutation == "nan":
        lines[1] = lines[1].rsplit(",", 1)[0]+",nan"
    if mutation == "mixed_host":
        lines[1] = lines[1].replace("customer-host-7", "different-host")
    if mutation == "extra_field":
        lines[0] += ",is_anomaly"
    with pytest.raises(ValueError):
        inspect_upload("\n".join(lines).encode(), **options())


def test_label_completeness_duplicates_and_alignment():
    points = observations()[200:]
    assert len(label_flags(labels(points), points, "customer-host-7")) == 160
    for raw in (labels(points[:-1]), labels(points)+labels(points).splitlines()[1]+b"\n",
                labels(observations()), labels(points).replace(b"customer-host-7", b"wrong"),
                labels(points).replace(b",0\r", b",2\r")):
        with pytest.raises(ValueError):
            label_flags(raw, points, "customer-host-7")


def run_upload(tmp_path, *, labelled=False, method="fixed_threshold", delta=0):
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.workflow import run
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    data, state = tmp_path / "data", tmp_path / "state"
    points = observations(delta)
    prepare_upload(data, encode_csv(points), labels=labels(points[200:]) if labelled else None,
                   label_source="受控注入；用户提供标签协议示例", **{**options(), "method": method})
    store = MetricsStore(state / "runtime.sqlite")
    gateway = make_gateway(store, mode="mock")
    knowledge = LegacySQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    outcome = asyncio.run(run(store, gateway, state=state, dataset_root=data, snapshot=knowledge.snapshot(), knowledge=knowledge,
        image=image, task_id="upload-case", task_input={"requirement": "检测内存升高", "anomaly_target": "upper", "explicit_constraints": {"threshold": 85.0}}))
    directory = Path(outcome["directory"])
    report = json.loads((directory / "report.json").read_text())
    assert outcome["status"] == report.get("completion_status", report["status"])
    assert outcome["stage_status"] == report["stage_status"]
    return report, directory, store, data


@pytest.mark.parametrize("labelled,method", [(False,"fixed_threshold"), (True,"fixed_threshold"), (False,"rolling_mad")])
def test_real_docker_upload_and_isolated_benchmark(tmp_path, monkeypatch, labelled, method):
    from factory.metrics.charts import read_curve
    from factory.metrics.reports import export_run
    report, directory, store, data = run_upload(tmp_path, labelled=labelled, method=method)
    assert report["status"] == "COMPLETED", report.get("failure")
    assert len(report["candidates"]) == 1 and report["selection"]["status"] == "USER_PRESELECTED_METHOD"
    assert report["benchmark"]["execution_status"] == "SUCCEEDED", report["benchmark"]
    assert report["benchmark"]["binding"]["manifest_sha256"] != report["bindings"]["manifest_sha256"]
    curve = read_curve(directory, report["curves"]["detection"])
    assert [r["value"] for r in curve["rows"]] == [p.value for p in observations()]
    assert curve["rows"][0]["host_id"] == "customer-host-7"
    assert all(r["score"] is None for r in curve["rows"] if r["status"] != "ok")
    if labelled:
        assert report["final"]["point"]["total"] == 160
        truth = report["final"]["truth_events"][0]
        predicted = report["final"]["predicted_events"][0]
        assert predicted["start_at"] > truth["start_at"]
    else:
        assert "point" not in report["final"] and "truth_events" not in report["final"]
        assert UNKNOWN == report["final"]["notice"]
        assert all("label" not in r for r in curve["rows"])
    with store._transaction() as db:
        prompts = [store.document(r[0]) for r in db.execute("SELECT reference FROM task_artifacts WHERE role='model-prompt'")]
    text = json.dumps(prompts)
    assert "user-labels" not in text and "2026-08-01T04:10" not in text and "independent-benchmark" not in text
    assert json.loads((directory / "publication.json").read_text())["status"] == "PUBLISHED"
    from factory.metrics.publication import publication_payload
    assert publication_payload(report)['receipt']['status'] == 'PUBLISHED'
    export_run(store, directory, tmp_path / "delivery.zip", dataset_root=data)
    from streamlit.testing.v1 import AppTest
    from factory.metrics.model import ModelGateway
    from execution.metrics_runner import MetricsRunner
    def forbidden(*args, **kwargs): raise AssertionError("read-only review must not run model or detector")
    monkeypatch.setattr(ModelGateway, "ask", forbidden)
    monkeypatch.setattr(MetricsRunner, "detector", forbidden)
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(directory.parents[1]))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=15)
    assert not app.exception
    from tests.metrics.test_app import nav
    nav(app, "查看结果")
    assert any("数据来源：上传CSV" in str(e.value) for e in app.caption)
    specs = app.get("vega_lite_chart")
    assert specs
    chart_spec = json.loads(specs[0].proto.spec)
    assert '"utc"' in json.dumps(chart_spec)
    if not labelled:
        assert "真实标签" not in json.dumps(chart_spec, ensure_ascii=False)
    nav(app, "创建任务")
    app.button(key="example-内存缓慢漂移").click().run(timeout=15)
    nav(app, "查看结果")
    assert not app.exception and any("customer-host-7" in str(e.value) for e in app.caption)
    curve_file = directory / report["curves"]["detection"]["path"]
    curve_file.write_text(curve_file.read_text()+" ")
    with pytest.raises(ValueError, match="digest"):
        read_curve(directory, report["curves"]["detection"])


def test_upload_mode_without_file_disables_submit(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(tmp_path / "ui"))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run()
    app.button(key="example-上传 CSV").click().run()
    assert not app.exception and next(b for b in app.button if b.label == "生成并验证").disabled
    assert not (tmp_path / "ui").exists()


def test_real_docker_future_values_do_not_change_past_outputs(tmp_path):
    from contracts.metrics import FixedConfig, MADConfig
    from factory.metrics.runtime import MetricsStore
    from execution.metrics_runner import MetricsRunner
    from factory.metrics.workflow import role_scores
    from tests.metrics.test_runtime import task
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    store = MetricsStore(tmp_path / "runtime.sqlite")
    store.create_task(task())
    runner = MetricsRunner(store, store.artifact_store, tmp_path / "packages", tmp_path / "work", image=image)
    points = observations()
    changed = [p if i < 280 else p.model_copy(update={"value": 99.}) for i, p in enumerate(points)]
    for method, config in (("fixed", FixedConfig(threshold=85)), ("mad", MADConfig())):
        source = (Path(__file__).resolve().parents[2] / f"materials/metrics/reference_{method}.py").read_text()
        left = role_scores(runner, "metrics-1", source, config, points[:60], points[140:], 60)
        right = role_scores(runner, "metrics-1", source, config, points[:60], changed[140:], 60)
        assert left["scores"][:140] == right["scores"][:140]


def test_benchmark_failure_does_not_repair_or_hide_upload_success(tmp_path, monkeypatch):
    import factory.metrics.workflow as workflow
    original = workflow.role_scores
    def fail_benchmark(runner, task_id, source, config, train, points, prefix):
        if train[0].host_id == "sim-host-a":
            raise ValueError("controlled benchmark execution failure")
        return original(runner, task_id, source, config, train, points, prefix)
    monkeypatch.setattr(workflow, "role_scores", fail_benchmark)
    report, directory, store, _ = run_upload(tmp_path)
    assert report["final"]["execution_status"] == "SUCCEEDED"
    assert report["stage_status"]["benchmark"] == "FAILED"
    assert "evaluation" not in report["benchmark"] and len(report["candidates"][0]["versions"]) == 1
    with store._transaction() as db:
        ops = list(db.execute("SELECT resource FROM operations WHERE task_id='upload-case'"))
    assert not any(row[0] == "repair" for row in ops)


def test_actual_mad_calibration_gap_keeps_engineering_result_and_never_scores_upload(tmp_path, monkeypatch):
    original = observations
    def missing_reference(delta=0):
        return [p.model_copy(update={"value": None}) if 61 <= i < 200 else p for i, p in enumerate(original(delta))]
    monkeypatch.setattr(__import__(__name__, fromlist=["observations"]), "observations", missing_reference)
    report, directory, _, _ = run_upload(tmp_path, method="rolling_mad")
    assert report["status"] == "NEEDS_INPUT"
    assert "CALIBRATION_INSUFFICIENT_SCORES" in report["failure"]["message"]
    assert report["stage_status"]["engineering"] == "PASSED"
    assert report["stage_status"]["detection"] == "NOT_EVALUATED"
    assert not report["final_test_executed"] and not (directory / "detection-points.csv").exists()


def test_two_different_csv_runs_keep_distinct_bindings_and_actual_scores(tmp_path):
    from factory.metrics.upload import read_curve
    first, first_dir, _, _ = run_upload(tmp_path / "first", delta=0)
    second, second_dir, _, _ = run_upload(tmp_path / "second", delta=1)
    assert first["data_source"]["sha256"] != second["data_source"]["sha256"]
    assert first["bindings"]["manifest_sha256"] != second["bindings"]["manifest_sha256"]
    a = read_curve(first_dir, first["curves"]["detection"])
    b = read_curve(second_dir, second["curves"]["detection"])
    left = next(r for r in a["rows"] if r["role"] == "detection")
    right = next(r for r in b["rows"] if r["role"] == "detection")
    assert right["value"] == left["value"] + 1 and right["score"] == left["score"] + 1


def test_large_curve_window_keeps_missing_anomalies_and_full_metrics(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    from factory.metrics.model import ModelGateway
    from execution.metrics_runner import MetricsRunner
    original_points = observations
    def large_points(delta=0):
        start = original_points()[0].timestamp
        return [MetricPoint(timestamp=start+timedelta(minutes=i), host_id="customer-host-7",
            value=None if 2200 <= i < 2204 else float(91 if 2400 <= i < 2500 else 40)) for i in range(3000)]
    monkeypatch.setattr(__import__(__name__, fromlist=["observations"]), "observations", large_points)
    report, directory, _, _ = run_upload(tmp_path)
    frozen = (directory / "report.json").read_bytes()
    def forbidden(*a, **k): raise AssertionError("window changes must only read saved outputs")
    monkeypatch.setattr(ModelGateway, "ask", forbidden)
    monkeypatch.setattr(MetricsRunner, "detector", forbidden)
    captured = []
    render = st.altair_chart
    def chart(spec, **kwargs):
        captured.append(spec.to_dict())
        return render(spec, **kwargs)
    monkeypatch.setattr(st, "altair_chart", chart)
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(directory.parents[1]))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=15)
    assert not app.exception
    from tests.metrics.test_app import nav
    nav(app, "查看结果")
    def point_tables(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from point_tables(child)
        elif isinstance(value, list):
            if value and isinstance(value[0], dict) and {"timestamp", "value"} <= value[0].keys():
                yield value
            else:
                for child in value:
                    yield from point_tables(child)
    points = next(point_tables(captured[0]))
    assert len(points) == 2000
    assert sum(p["value"] is None for p in points) == 4 and any(p["prediction"] for p in points)
    offset = next(e for e in app.number_input if "图形窗口起始点" in e.label)
    offset.set_value(0).run(timeout=15)
    assert not app.exception and (directory / "report.json").read_bytes() == frozen
    assert report["final"]["coverage"]["value"] == pytest.approx(2799/2800)


def test_over_limit_upload_rejected_before_preparation(tmp_path):
    from factory.metrics.upload import prepare_upload as normalize, comparison_split
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    raw = encode_csv([MetricPoint(timestamp=start+timedelta(minutes=i), host_id='customer-host-7', value=40.)
                      for i in range(50001)])
    for action in (lambda: inspect_upload(raw, **options()),
                   lambda: normalize(tmp_path/'never-created', raw, **options()),
                   lambda: comparison_split(50001)):
        with pytest.raises(ValueError, match='50000 point limit'):
            action()
    assert not (tmp_path/'never-created').exists()
