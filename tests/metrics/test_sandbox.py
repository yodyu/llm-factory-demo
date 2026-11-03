import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from contracts.metrics import FixedConfig, MADConfig
from execution.metrics_runner import CandidateFailure, MetricsRunner, check_source
from factory.metrics.data import CausalPreprocessor
from factory.metrics.runtime import MetricsStore
from tests.metrics.test_core import points
from tests.metrics.test_runtime import task

ROOT = Path(__file__).resolve().parents[2]


def test_static_profile_cannot_import_reference_or_unapproved_dependencies():
    for source in ("from factory.metrics.reference import create_detector", "import sklearn", "x=eval('1')"):
        with pytest.raises(CandidateFailure):
            check_source(source)
    with pytest.raises(CandidateFailure, match="MISSING_ENTRYPOINT"):
        check_source("import math")


def test_schema_feedback_includes_actual_value_and_expected_object_type():
    from execution.metrics_runner import DetectorSession

    point = CausalPreprocessor().step(points([1.0])[0])
    class Wire:
        def request(self, _):
            return {"ok": True, "result": {"timestamp": point.timestamp.isoformat(), "host_id": point.host_id,
                    "status": "insufficient_history", "score": None, "evidence": None}}
    with pytest.raises(CandidateFailure) as caught:
        DetectorSession(Wire()).score_one(point)
    feedback = caught.value.feedback
    assert feedback["actual"]["evidence"] is None
    assert feedback["expected_schema"]["properties"]["evidence"]["type"] == "object"
    assert feedback["issues"][0]["field"] == ["evidence"]


def test_stability_comparison_accepts_equal_string_and_null_evidence():
    from factory.metrics.validation import _same
    from contracts.metrics import Score
    base = {"timestamp": points([1.0])[0].timestamp, "host_id": "h", "status": "ok", "score": 1.0,
            "evidence": {"threshold": 5.0, "direction": "upper", "optional": None}}
    left = Score.model_validate(base)
    assert _same(left, Score.model_validate(base))
    assert not _same(left, Score.model_validate({**base, "evidence": {"threshold": 5.0, "direction": "lower", "optional": None}}))
    assert not _same(left, Score.model_validate({**base, "score": 2.0}))


@pytest.fixture
def sandbox(tmp_path):
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    store = MetricsStore(tmp_path / "state" / "metrics.sqlite")
    store.create_task(task())
    runner = MetricsRunner(store, store.artifact_store, tmp_path / "packages", tmp_path / "work", image=image)
    yield runner, store
    runner.cleanup_orphans()


@pytest.mark.parametrize("method,config,values,expected", [
    ("fixed", FixedConfig(threshold=5.0), [4.0, 5.0, 6.0], [-1, 0, 1]),
    ("mad", MADConfig(window=3, min_history=3), [1.0, 2.0, 3.0, 6.0], [None, None, None, 4 / 1.4826]),
])
def test_real_docker_pointwise_semantics_state_reload_and_mount_isolation(sandbox, method, config, values, expected):
    runner, store = sandbox
    source = (ROOT / f"materials/metrics/reference_{method}.py").read_text()
    with runner.detector("metrics-1", source) as detector:
        detector.fit(config, points([0.0, 1.0, 2.0, 3.0]))
        # Inspect only containers bearing this new namespace, not existing POC containers.
        listing = subprocess.run([*runner.docker_command, "ps", "-q", "--filter", "label=llm-factory.managed=metrics-v1"],
                                 capture_output=True, text=True, check=True).stdout.split()
        assert len(listing) == 1
        info = json.loads(subprocess.run([*runner.docker_command, "inspect", listing[0]], capture_output=True,
                                         text=True, check=True).stdout)[0]
        assert info["Config"]["User"] == "65534:65534"
        assert info["HostConfig"]["NetworkMode"] == "none" and info["HostConfig"]["ReadonlyRootfs"]
        assert len(info["Mounts"]) == 1 and info["Mounts"][0]["Destination"] == "/code" and not info["Mounts"][0]["RW"]
        assert {p.name for p in Path(info["Mounts"][0]["Source"]).iterdir()} == {"algorithm.py", "worker.py"}
        prep = CausalPreprocessor()
        output = [detector.score_one(prep.step(point)) for point in points(values)]
        for actual, wanted in zip(output, expected):
            assert actual.score is None if wanted is None else actual.score == pytest.approx(wanted)
        state = detector.call("save")
        point = prep.step(points([0.0] * len(values) + [7.0])[-1])
        first = detector.score_one(point)
        detector.call("load", state=state)
        assert detector.score_one(point) == first
        detector.reset()
        assert detector.score_one(CausalPreprocessor().step(points(values)[0])) == output[0]
    assert not list(runner.work_root.glob("run-*"))


def test_real_docker_reports_candidate_line(sandbox):
    runner, _ = sandbox
    source = (ROOT / "materials/metrics/reference_fixed.py").read_text().replace(
        'value = point["value"]', 'value = point["missing_field"]')
    with runner.detector("metrics-1", source) as detector:
        detector.fit(FixedConfig(threshold=5.0), points([1.0]))
        with pytest.raises(CandidateFailure) as caught:
            detector.score_one(CausalPreprocessor().step(points([1.0])[0]))
        assert caught.value.feedback["type"] == "KeyError"
        assert caught.value.feedback["line"] > 0
        assert "missing_field" in caught.value.feedback["message"]


@pytest.mark.parametrize("method,config", [("fixed", FixedConfig(threshold=5.0)),
                                         ("mad", MADConfig(window=3, min_history=3))])
def test_method_validators_and_injected_failure(sandbox, method, config):
    from factory.metrics.validation import validate_candidate

    runner, _ = sandbox
    source = (ROOT / f"materials/metrics/reference_{method}.py").read_text()
    if method == "fixed":
        source = source.replace('"evidence": {"threshold": self.config["threshold"]}',
                                '"evidence": {"threshold": self.config["threshold"], "direction": "upper", "optional": None}')
    report = validate_candidate(runner, "metrics-1", source, config,
                                candidate_id=method, version=0, origin="reference")
    assert report["passed"], report
    if method == "fixed":
        faulty = source.replace('value - self.config["threshold"]', 'value + self.config["threshold"]')
    else:
        faulty = source.replace('delta / scale', 'delta / (scale + 1)')
    failed = validate_candidate(runner, "metrics-1", faulty, config,
                                candidate_id=method, version=0, origin="fault_injection")
    assert not failed["passed"] and failed["repairable"]
    last = failed["checks"][-1]
    assert last["difference"]["code"] == "METHOD_DIFFERENCE"
    assert last["development_input"] and last["difference"]["expected"] != last["difference"]["actual"]


def test_failed_cli_check_has_nonzero_exit_and_keeps_report(sandbox, tmp_path):
    runner, _ = sandbox
    source = tmp_path / "faulty.py"
    source.write_text((ROOT / "materials/metrics/reference_fixed.py").read_text().replace(
        'value - self.config["threshold"]', 'value + self.config["threshold"]'))
    report = tmp_path / "failed.json"
    result = subprocess.run([sys.executable, "-m", "factory.metrics", "sandbox-check",
                            "--source", str(source), "--method", "fixed_threshold", "--origin", "fault_injection",
                            "--image", runner.image, "--state", str(tmp_path / "cli-state"), "--output", str(report)],
                            capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    data = json.loads(report.read_text())
    assert data["passed"] is False and data["origin"] == "fault_injection"
    assert data["checks"][-1]["difference"]["code"] == "METHOD_DIFFERENCE"
    assert data["generation_evidence_verified"] is False

@pytest.mark.parametrize('method,config', [('fixed', FixedConfig(threshold=85)), ('mad', MADConfig())])
def test_real_docker_upload_limit_all_roles(sandbox, tmp_path, method, config):
    import time
    from datetime import datetime, timedelta, timezone
    from contracts.metrics import MetricPoint, MetricsDataset
    from factory.metrics.data import encode_csv, load_role
    from factory.metrics.upload import prepare_upload, simple_upload_options
    from factory.metrics.execution_ops import role_scores, decode_scores
    from factory.metrics.reference import create_detector
    from factory.metrics.validation import _same
    from factory.metrics.evaluation import alarms
    runner, _ = sandbox
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = [MetricPoint(timestamp=start+timedelta(minutes=i), host_id='limit-host',
        value=None if 24995 <= i < 25005 else float(35+i%3)) for i in range(50000)]
    raw = encode_csv(observations)
    root = tmp_path/'data'
    prepare_upload(root, raw, **simple_upload_options(raw, scenario='cpu_spike', display_name='limit.csv'))
    manifest = MetricsDataset.model_validate_json((root/'manifest.json').read_text())
    source = (ROOT/f'materials/metrics/reference_{method}.py').read_text()
    train = load_role(root, manifest, 'train')
    started = time.monotonic()
    for role in ('train', 'calibration', 'development', 'test'):
        values = load_role(root, manifest, role)
        prefix = manifest.roles[role].prefix_points
        actual = role_scores(runner, 'metrics-1', source, config, train, values, prefix)
        reference = create_detector(config)
        reference.fit(train)
        reference.reset()
        prep = CausalPreprocessor()
        expected = [reference.score_one(prep.step(p)) for p in values]
        decoded = decode_scores(actual)
        assert len(decoded) == len(expected) and all(_same(e, a) for e, a in zip(expected, decoded))
        assert alarms(decoded[prefix:], threshold=0., persistence_points=2) == alarms(expected[prefix:], threshold=0., persistence_points=2)
        print(f'{method} {role}: points={len(values)} scoring_seconds={actual["elapsed_seconds"]:.3f}')
    print(f'{method} 50000-point all-role wall_seconds={time.monotonic()-started:.3f}')


def test_role_allocation_is_bounded_and_uses_trusted_point_counts():
    from execution.metrics_runner import role_budget
    from execution.runner import OUTPUT_LIMIT
    budget = role_budget(24960, 60)
    assert budget.output_bytes == OUTPUT_LIMIT + 24960 * 4096
    assert budget.seconds == pytest.approx(109.84)
    assert role_budget(50000, 50000).seconds == 210
    for n in (-1, 50001, True, 1.5):
        with pytest.raises(ValueError):
            role_budget(n, 60)


@pytest.mark.parametrize('fault,expected', [('large', 'CANDIDATE_ERROR'), ('logs', 'RESOURCE_LIMIT'), ('loop', 'CODE_TIMEOUT')])
def test_real_docker_large_allocation_keeps_individual_limits(sandbox, fault, expected):
    from contracts import FactoryError
    runner, _ = sandbox
    source = (ROOT/'materials/metrics/reference_fixed.py').read_text()
    body = {'large': 'return {"padding": "x" * (129 * 1024)}',
            'logs': 'while True: print("x" * 4096)',
            'loop': 'while True: pass'}[fault]
    source += '\nclass BadDetector(Detector):\n    def score_one(self, point):\n        '+body+'\ndef create_detector(config):\n    return BadDetector(config)\n'
    runner.timeout_seconds = .5 if fault == 'loop' else 10
    with runner.detector('metrics-1', source, point_count=50000, fit_count=60) as detector:
        detector.fit(FixedConfig(threshold=85), points([1.]))
        with pytest.raises((CandidateFailure, FactoryError)) as caught:
            detector.score_one(CausalPreprocessor().step(points([1.])[0]))
        error = caught.value
        assert (error.feedback['code'] if isinstance(error, CandidateFailure) else error.code.value) == expected
