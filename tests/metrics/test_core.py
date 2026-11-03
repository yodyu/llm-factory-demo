"""Run in the configured Linux checkout and its independent .venv."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from contracts.metrics import (
    Event, EvaluationPolicy, FixedConfig, MADConfig, MetricPoint, MetricsDataset, Score,
)
from factory.metrics.data import CausalPreprocessor, encode_csv, load_role, read_csv
from factory.metrics.evaluation import (
    alarms, calibrate, evaluate, events_from_flags, match_events, nearest_rank, select_development,
)
from factory.metrics.reference import create_detector, linear_quantile
from factory.metrics.synthetic import SCENARIOS, generate, write_dataset
from factory.runtime.artifacts import digest

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def points(values):
    return [MetricPoint(timestamp=START + timedelta(minutes=i), host_id="h", value=v)
            for i, v in enumerate(values)]


def replay(config, values, *, train=(0.0, 1.0, 2.0, 3.0)):
    detector, prep = create_detector(config), CausalPreprocessor()
    detector.fit(points(train))
    return detector, [detector.score_one(prep.step(p)) for p in points(values)]


def score(index, value, status="ok"):
    return Score(timestamp=START + timedelta(minutes=index), host_id="h", status=status, score=value)


def test_csv_preserves_missing_and_rejects_grid_corruption():
    original = points([1.0, None, 3.0])
    assert read_csv(encode_csv(original), host_id="h", sampling_seconds=60, valid_range=(0, 100)) == original
    bad = encode_csv([original[0], original[2]])
    with pytest.raises(ValueError, match="row 3"):
        read_csv(bad, host_id="h", sampling_seconds=60, valid_range=(0, 100))


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "101", "abc"])
def test_csv_invalid_numbers(value):
    raw = f"timestamp,host_id,value\n2026-01-01T00:00:00Z,h,{value}\n".encode()
    with pytest.raises(ValueError, match="row 2"):
        read_csv(raw, host_id="h", sampling_seconds=60, valid_range=(0, 100))


@pytest.mark.parametrize("timestamps", [
    ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
    ["2026-01-01T00:01:00Z", "2026-01-01T00:00:00Z"],
    ["2026-01-01T00:00:00Z", "2026-01-01T00:01:01Z"],
    ["2026-01-01T00:00:00+08:00"],
])
def test_bad_timestamp_sequences(timestamps):
    raw = ("timestamp,host_id,value\n" + "".join(f"{t},h,1\n" for t in timestamps)).encode()
    with pytest.raises(ValueError):
        read_csv(raw, host_id="h", sampling_seconds=60, valid_range=(0, 100))


def test_causal_forward_fill_never_uses_future():
    prep = CausalPreprocessor()
    result = [prep.step(p) for p in points([None, 7.0, None, None, None, None, 9.0])]
    assert [p.value for p in result] == [None, 7, 7, 7, 7, None, 9]
    assert [p.original_present for p in result] == [False, True, False, False, False, False, True]
    assert result[4].missing_streak == 3 and result[5].imputation == "unavailable"


@pytest.mark.parametrize("direction,expected", [("upper", [-1, 0, 1]), ("lower", [1, 0, -1])])
def test_fixed_threshold_strict_boundary(direction, expected):
    _, result = replay(FixedConfig(threshold=5.0, direction=direction), [4.0, 5.0, 6.0])
    assert [p.score for p in result] == expected
    assert alarms(result, threshold=0, persistence_points=1) == [v > 0 for v in expected]


@pytest.mark.parametrize("direction,current,expected", [
    ("upper", 6.0, 4 / 1.4826), ("lower", 0.0, 2 / 1.4826),
    ("two_sided", 0.0, 2 / 1.4826),
])
def test_mad_hand_calculation_excludes_current(direction, current, expected):
    _, result = replay(MADConfig(window=3, min_history=3, direction=direction), [1.0, 2.0, 3.0, current])
    assert [p.status for p in result[:3]] == ["insufficient_history"] * 3
    assert result[3].score == pytest.approx(expected)
    assert result[3].evidence["median"] == 2


def test_imputation_does_not_accelerate_cold_start():
    _, result = replay(MADConfig(window=5, min_history=3), [1.0, None, 3.0, 4.0, 5.0])
    assert [p.status for p in result[:4]] == ["insufficient_history"] * 4
    assert result[4].status == "ok"


def test_missing_slots_expire_old_history():
    _, result = replay(MADConfig(window=3, min_history=2), [1.0, 1.0, None, None, None, None, 2.0])
    assert result[2].status == "ok"
    assert result[-2].status == "missing_input"
    assert result[-1].status == "insufficient_history"


def test_constant_history_uses_training_floor_and_resets():
    detector, result = replay(MADConfig(window=3, min_history=2), [1.0, 1.0, 1.0, 2.0], train=(1.0, 1.0))
    assert result[2].score == 0
    assert result[3].score == pytest.approx(1e9)
    detector.reset()
    assert detector.score_one(CausalPreprocessor().step(points([1.0])[0])).status == "insufficient_history"


def test_training_quantile_and_calibration_quantile_are_distinct():
    assert linear_quantile([0, 10, 20, 30], 0.25) == 7.5
    assert nearest_rank([0, 10, 20, 30], 0.25) == 0
    scores = [score(i, float(i)) for i in range(160)]
    result = calibrate(scores, quantile=0.99, prefix_points=60)
    assert result["threshold"] == 158 and result["score_count"] == 100 and not result["labels_used"]
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        calibrate(scores[:-1], quantile=0.99, prefix_points=60)


def test_state_reload_and_future_invariance():
    config = MADConfig(window=3, min_history=2)
    detector, first = replay(config, [1.0, 2.0, 3.0])
    raw = detector.save_state()
    restored = create_detector(config)
    restored.load_state(raw)
    p = CausalPreprocessor().step(points([1, 2, 3, 99.0])[-1])
    assert detector.score_one(p) == restored.score_one(p)
    _, changed = replay(config, [1.0, 2.0, 3.0, 1e9])
    assert first == changed[:3]
    with pytest.raises(ValueError, match="mismatch"):
        create_detector(MADConfig(window=4, min_history=2)).load_state(raw)
    with pytest.raises(ValueError):
        restored.load_state(raw.replace('"scale_floor":', '"scale_floor":1,"scale_floor":'))


def test_persistence_does_not_backfill_and_missing_resets():
    scores = [score(0, 1), score(1, 1), score(2, None, "missing_input"), score(3, 1), score(4, 1)]
    assert alarms(scores, threshold=0, persistence_points=2) == [False, True, False, False, True]


def test_event_half_open_matching_and_long_alarm_only_once():
    grid = points([1.0] * 6)
    truth = events_from_flags(grid, [True, True, False, True, True, False], metric="cpu", sampling_seconds=60, id_prefix="t")
    predicted = events_from_flags(grid, [False, True, True, True, True, False], metric="cpu", sampling_seconds=60, id_prefix="p")
    result = match_events(predicted, truth)
    assert (result["tp"], result["fp"], result["fn"]) == (1, 0, 1)
    assert result["pairs"][0]["delay_seconds"] == 60
    boundary = Event(event_id="end", host_id="h", metric="cpu", start_at=grid[2].timestamp,
                     trigger_at=grid[2].timestamp, end_at=grid[3].timestamp)
    assert match_events([boundary], truth)["tp"] == 0


def test_matching_earliest_trigger_and_host_scope():
    grid = points([1.0] * 6)
    truth = events_from_flags(grid, [True] * 6, metric="cpu", sampling_seconds=60, id_prefix="t")
    pred = events_from_flags(grid, [False, True, False, True, False, False], metric="cpu", sampling_seconds=60, id_prefix="p")
    assert match_events(list(reversed(pred)), truth)["pairs"][0]["prediction_id"] == "p-0000"
    other = [e.model_copy(update={"host_id": "other"}) for e in pred]
    assert match_events(other, truth)["tp"] == 0
    with pytest.raises(ValueError, match="overlapping"):
        match_events(pred, truth + [truth[0].model_copy(update={"event_id": "overlap"})])


def report(scores, labels, *, prefix=0, persistence=1):
    return evaluate(points([1.0] * len(scores)), scores, labels, host_id="h", metric="cpu", sampling_seconds=60,
                    prefix_points=prefix, threshold=0, elapsed_seconds=0.01,
                    policy=EvaluationPolicy(persistence_points=persistence))


def test_abstentions_account_for_entire_denominator():
    result = report([score(0, None, "missing_input"), score(1, None, "insufficient_history"), score(2, 0)],
                    [True, False, False])
    p = result["point"]
    assert (p["tp"], p["fp"], p["fn"], p["tn"], p["abstained_normal"]) == (0, 0, 1, 1, 1)
    assert sum(p[k] for k in ("tp", "fp", "fn", "tn", "abstained_normal")) == p["total"]
    assert result["coverage"]["value"] == 1 / 3
    assert p["precision"]["value"] is None and p["f1"]["value"] == 0
    assert result["engineering_status"] == "COVERAGE_FAILED"
    assert result["acceptance_status"] == "MEASURED_NO_ACCEPTANCE_THRESHOLD"


def test_empty_prediction_denominators_and_prefix_persistence_reset():
    result = report([score(0, 1), score(1, 1), score(2, 1), score(3, 1)],
                    [False, False, True, True], prefix=2, persistence=2)
    assert result["point"]["tp"] == 1 and result["point"]["fn"] == 1
    assert result["event"]["pairs"][0]["delay_seconds"] == 60
    assert result["normal_false_alarms_per_host_hour"]["value"] is None
    quiet = report([score(0, 0)], [False])
    assert quiet["event"]["f1"]["value"] is None
    assert quiet["point"]["recall"]["null_reason"] == "no_true_anomalies"


def test_false_alarm_normal_time_denominator_and_duplicate_events():
    result = report([score(i, float(v)) for i, v in enumerate([1, 0, 1, 0, 1, 0])],
                    [False, False, True, True, True, True])
    assert result["event"]["tp"] == 1 and result["event"]["fp"] == 2
    assert len(result["event"]["unmatched_prediction_ids"]) == 2
    assert result["normal_false_alarms_per_host_hour"]["value"] == 30


def test_interface_failure_is_not_a_successful_abstention():
    with pytest.raises(ValueError, match="length"):
        evaluate(points([1.0]), [], [True], host_id="h", metric="cpu", sampling_seconds=60,
                 prefix_points=0, threshold=0, elapsed_seconds=0,
                 policy=EvaluationPolicy())
    with pytest.raises(ValueError, match="mismatch"):
        report([score(1, 1)], [True])
    for status, value in [("ok", None), ("missing_input", 0), ("ok", math.nan)]:
        with pytest.raises(ValidationError):
            score(0, value, status)


def test_selection_only_uses_development_and_handles_normal_only_labels():
    good = report([score(0, 1)], [True])
    quiet = report([score(0, 0)], [False])
    candidates = [{"candidate_id": name, "role": "development", "report": good} for name in ("b", "a")]
    assert select_development(candidates)["selected"] == "a"
    normal_only = select_development([{"candidate_id": "q", "role": "development", "report": quiet}])
    assert normal_only["status"] == "SELECTED_NORMAL_ONLY" and normal_only["selected"] == "q"
    assert quiet['event']['f1']['value'] is None  # Selection does not invent an F1 value.
    with pytest.raises(ValueError, match="development"):
        select_development([{**candidates[0], "role": "test"}])
    assert select_development([])["status"] == "NO_ELIGIBLE_CANDIDATE"


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_synthetic_reproducibility_role_isolation_and_independent_labels(scenario, tmp_path):
    bundle = generate(scenario)
    assert bundle["observations"] == generate(scenario)["observations"]
    labels = json.loads(bundle["labels"])
    assert not any(labels["train"]) and not any(labels["calibration"])
    assert any(labels["development"]) and any(labels["test"])
    assert len(set(bundle["experiment"]["seeds"].values())) == 4
    assert all(not any(values[:60]) for values in labels.values())
    root = tmp_path / "data"
    write_dataset(root, bundle)
    manifest = MetricsDataset.model_validate(json.loads((root / "manifest.json").read_text()))
    assert len(load_role(root, manifest, "development")) == 300
    assert digest((root / "trusted" / "labels.json").read_bytes()) == bundle["experiment"]["labels_sha256"]
    # Reading an authorized role does not require or open the test file.
    (root / "test.csv").unlink()
    assert len(load_role(root, manifest, "train")) == 300
    (root / "train.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        load_role(root, manifest, "train")
    with pytest.raises(FileExistsError):
        write_dataset(root, bundle)


def test_reference_tool_works_without_test_observations_and_declares_origin(tmp_path):
    from factory.metrics.__main__ import reference_check

    root = tmp_path / "reference-demo"
    write_dataset(root, generate("memory_shift"))
    (root / "test.csv").unlink()
    result = reference_check(root, threshold=85)
    assert result["origin"] == "reference" and result["model_calls"] == 0
    assert result["final_test_executed"] is False
    assert len(result["candidates"]) == 2
    assert all(c["origin"] == "reference" and c["role"] == "development" for c in result["candidates"])


def test_strict_numeric_contracts_reject_unsupported_counter_and_unknown_methods():
    from contracts.metrics import CandidatePlan

    manifest = generate("cpu_spike")["manifest"].model_dump(mode="json")
    with pytest.raises(ValidationError):
        MetricsDataset.model_validate({**manifest, "metric_kind": "counter"})
    with pytest.raises(ValidationError):
        CandidatePlan(candidate_id="x", config={"method_id": "isolation_forest"},
                      parameter_sources={}, knowledge_ids=[], limitations=[])
    with pytest.raises(ValidationError):
        MADConfig(window=3, min_history=4)
