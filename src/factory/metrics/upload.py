"""Trusted upload preparation and frozen-result artifacts. No generated-code imports."""
from factory.metrics.capability_registry import registry, default_methods

import csv
import io
import json
from pathlib import Path

from contracts.metrics import MetricsDataset, RoleFile, utc_timestamp, MAX_UPLOAD_POINTS
from factory.metrics.data import MAX_CSV_BYTES, CausalPreprocessor, encode_csv, read_csv
from factory.metrics.evaluation import alarms, events_from_flags
from factory.metrics.knowledge import canonical
from factory.metrics.synthetic import SCENARIOS, generate, write_dataset
from factory.runtime.artifacts import digest

UNKNOWN = "已完成检测，但上传数据的精确率、召回率及漏检情况未知。"
BENCHMARK_NOTICE = "这些指标属于独立模拟基准，不代表上传数据的准确率或生产效果。"


def simple_upload_options(raw, *, scenario, display_name):
    """Infer only CSV metadata; reuse the existing strict validator and split protocol."""
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV 超过 16 MiB 上限")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != ["timestamp", "host_id", "value"]:
        raise ValueError("CSV 表头必须依次为 timestamp,host_id,value")
    first, second = next(reader, None), next(reader, None)
    if not first or not second or any(None in row or any(v is None for v in row.values()) for row in (first, second)):
        raise ValueError("CSV 列数不正确或数据不足；至少需要 201 个连续采样点")
    seconds = (utc_timestamp(second['timestamp']) - utc_timestamp(first['timestamp'])).total_seconds()
    if not seconds.is_integer() or not 1 <= seconds <= 86400:
        raise ValueError("采样间隔必须为 1～86400 的整数秒，时间须严格递增")
    metric, unit, _, upper = SCENARIOS[scenario]
    options = dict(display_name=display_name, host_id=first['host_id'], metric=metric, unit=unit,
                   metric_kind="rate" if scenario == "network_missing" else "gauge",
                   sampling_seconds=int(seconds), valid_range=(0., upper), fit_points=60,
                   history_points=200, method=None, direction="upper")
    if sum(1 for _ in reader) + 2 < 201:
        raise ValueError("至少需要 201 个采样点：前 60 点拟合、第 61～200 点校准，其后仅检测")
    return options


def upload_example(scenario):
    """Complete unlabelled format example, unrelated to any measured task."""
    from datetime import datetime, timedelta, timezone
    from contracts.metrics import MetricPoint
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    baseline = SCENARIOS[scenario][2]
    return encode_csv([MetricPoint(timestamp=start + timedelta(minutes=i), host_id="server-a", value=baseline)
                       for i in range(360)])


def read_curve(directory, binding):
    root = Path(directory).resolve()
    path = root / binding["path"]
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("unsafe curve artifact")
    raw = path.read_bytes()
    if digest(raw) != binding["sha256"]:
        raise ValueError("curve artifact digest mismatch")
    return json.loads(raw)


def label_flags(raw, points, host_id):
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("label CSV exceeds byte limit")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != ["timestamp", "host_id", "is_anomaly"]:
        raise ValueError("labels require timestamp,host_id,is_anomaly")
    allowed = {p.timestamp for p in points}
    values = {}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("invalid label column count")
        timestamp = utc_timestamp(row["timestamp"])
        value = row["is_anomaly"].lower()
        if row["host_id"] != host_id or timestamp not in allowed:
            raise ValueError("label host/time outside detection interval")
        if timestamp in values or value not in {"0", "1", "true", "false"}:
            raise ValueError("duplicate/conflicting or non-boolean label")
        values[timestamp] = value in {"1", "true"}
    missing = [p.timestamp.isoformat() for p in points if p.timestamp not in values]
    if missing:
        raise ValueError(f"incomplete labels: missing {len(missing)} slots; first={missing[0]}, last={missing[-1]}")
    return [values[p.timestamp] for p in points]


def describe(points, start, end, purpose):
    subset = points[start:end]
    return {"purpose": purpose, "points": len(subset), "start_at": subset[0].timestamp.isoformat(),
            "end_at_inclusive": subset[-1].timestamp.isoformat(),
            "missing_points": sum(p.value is None for p in subset)}


def inspect_upload(raw, *, display_name, host_id, metric, unit, metric_kind, sampling_seconds,
                   valid_range, fit_points, history_points, method, direction="upper"):
    from pydantic import TypeAdapter
    from contracts.base import Identifier
    TypeAdapter(Identifier).validate_python(metric)
    if unit not in {"percent", "ms", "bytes/s"} or metric_kind not in {"gauge", "rate"}:
        raise ValueError("supported units: percent/ms/bytes/s; gauge or converted rate only; raw counter unsupported")
    method = method or default_methods()[0]
    if direction not in registry().get(method).supported_directions:
        raise ValueError("unsupported method/direction")
    points = read_csv(raw, host_id=host_id, sampling_seconds=sampling_seconds, valid_range=valid_range)
    if len(points) > MAX_UPLOAD_POINTS:
        raise ValueError("CSV exceeds 50000 point limit")
    if not 1 <= fit_points < history_points < len(points):
        raise ValueError("require 1 <= fit_points < history_points < total points")
    if not any(p.value is not None for p in points[:fit_points]):
        raise ValueError("fit history has no observed values")
    if registry().get(method).calibration == "quantile" and history_points - fit_points < 100:
        raise ValueError(f"CALIBRATION_INSUFFICIENT_SCORES: at most {history_points-fit_points}/100; add at least {100-(history_points-fit_points)} calibration slots (100 valid scores required)")
    summary = {"type": "uploaded_csv", "display_name": Path(display_name).name[:160], "sha256": digest(raw),
               "host_id": host_id, "metric": metric, "unit": unit, "metric_kind": metric_kind,
               "sampling_seconds": sampling_seconds, "valid_range": list(valid_range),
               "method": method, "direction": direction, "fit_points": fit_points, "history_points": history_points,
               **describe(points, 0, len(points), "all observations"),
               "splits": [describe(points, 0, fit_points, "fit_history"),
                          describe(points, fit_points, history_points, "calibration_history"),
                          describe(points, history_points, len(points), "detection_only")],
               "normal_history_assumption": "用户假设历史参考适用且正常；系统未验证", "warmup_points": min(60, history_points)}
    return points, summary


def prepare_legacy_upload(destination, raw, *, labels=None, label_source=None, **options):
    points, summary = inspect_upload(raw, **options)
    fit, boundary = summary["fit_points"], summary["history_points"]
    flags = label_flags(labels, points[boundary:], summary["host_id"]) if labels is not None else None
    if flags is not None and not (label_source or "").strip():
        raise ValueError("declare user-provided label source")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    (destination / "trusted").mkdir(mode=0o700)
    (destination / "observations.csv").write_bytes(raw)
    roles = {}
    segments = {"train": (points[:fit], 0), "calibration": (points[max(0, fit-60):boundary], min(60, fit)),
                "development": (points[:boundary], min(60, boundary)), "test": (points[max(0, boundary-60):], min(60, boundary))}
    for role, (segment, prefix) in segments.items():
        content = encode_csv(segment)
        (destination / f"{role}.csv").write_bytes(content)
        roles[role] = RoleFile(path=f"{role}.csv", sha256=digest(content), prefix_points=prefix)
    # Labels remain exclusively in trusted storage; never part of role observations.
    summary["labels"] = None
    if flags is not None:
        (destination / "trusted" / "user-labels.csv").write_bytes(labels)
        summary["labels"] = {"sha256": digest(labels), "source": label_source[:500], "status": "用户提供标签",
                             "coverage": 1.0, "points": len(flags)}
    summary["benchmark"] = {"status": "NOT_APPLICABLE", "reason": "no exact supported metric/unit/range/direction match"}
    for scenario, (metric, unit, _, upper) in SCENARIOS.items():
        kind = "rate" if scenario == "network_missing" else "gauge"
        if (summary["metric"], summary["unit"], summary["metric_kind"], summary["sampling_seconds"], summary["valid_range"], summary["direction"]) == (metric, unit, kind, 60, [0.0, upper], "upper"):
            bundle = generate(scenario)
            write_dataset(destination / "benchmark", bundle)
            summary["benchmark"] = {"status": "READY", "scenario": scenario, "generator_version": bundle["experiment"]["generator_version"],
                                    "manifest_sha256": digest((destination / "benchmark" / "manifest.json").read_bytes()),
                                    "experiment_sha256": digest((destination / "benchmark" / "trusted" / "experiment.json").read_bytes()),
                                    "policy": "fixed before planning; independent refit/calibration; never selection or repair"}
            break
    identity = digest(canonical(summary).encode())
    manifest = MetricsDataset(dataset_id="upload-" + identity[7:31], host_id=summary["host_id"], metric=summary["metric"],
        unit=summary["unit"], metric_kind=summary["metric_kind"], sampling_seconds=summary["sampling_seconds"], valid_range=summary["valid_range"], roles=roles)
    (destination / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    (destination / "upload.json").write_text(canonical(summary))
    return summary


def comparison_split(total, history_points=200):
    """Chronological disjoint scoring regions; prefix history is never scored."""
    if total > MAX_UPLOAD_POINTS:
        raise ValueError("CSV exceeds 50000 point limit")
    if total - history_points < 2:
        raise ValueError("至少需要 202 点：历史之后须分别保留开发段与最终测试段")
    boundary = history_points + (total - history_points) // 2
    return {"development_end": boundary, "development_points": boundary - history_points,
            "test_points": total - boundary}


def prepare_upload(destination, raw, *, labels=None, label_source=None, **options):
    """Normalize CSV into the same four-role dataset consumed by simulations.

    Legacy artifacts remain readable; only newly prepared input is normalized.
    Label values are evaluator-only and never determine chronological boundaries.
    """
    points, preview = inspect_upload(raw, **options)
    split = comparison_split(len(points), preview["history_points"])
    summary = prepare_legacy_upload(destination, raw, labels=labels, label_source=label_source, **options)
    root = Path(destination)
    fit, history, boundary = summary["fit_points"], summary["history_points"], split["development_end"]
    roles, role_labels = {}, {}
    flags = label_flags(labels, points[history:], summary["host_id"]) if labels is not None else None
    segments = {"train": (0, fit, 0), "calibration": (max(0, fit-60), history, min(60, fit)),
                "development": (max(0, history-60), boundary, min(60, history)),
                "test": (max(0, boundary-60), len(points), min(60, boundary))}
    for role, (start, end, prefix) in segments.items():
        content = encode_csv(points[start:end])
        (root / f"{role}.csv").write_bytes(content)
        roles[role] = RoleFile(path=f"{role}.csv", sha256=digest(content), prefix_points=prefix)
        role_labels[role] = None if flags is None else (
            [False]*(end-start) if role in {"train", "calibration"} else
            [False]*prefix + flags[:boundary-history] if role == "development" else
            [False]*prefix + flags[boundary-history:])
    summary.pop("method", None)
    summary.update(pipeline="four-role-comparison/1", allowed_methods=default_methods(),
                   **split, selection_policy="development_event_f1_with_labels_else_engineering_only",
                   splits=[describe(points, 0, fit, "train"), describe(points, fit, history, "calibration"),
                           describe(points, history, boundary, "development"), describe(points, boundary, len(points), "test")],
                   warmup_policy="each role starts fresh and uses only preceding observations; warmup never scored")
    manifest = MetricsDataset(dataset_id="upload-" + digest(canonical(summary).encode())[7:31], host_id=summary["host_id"],
        metric=summary["metric"], unit=summary["unit"], metric_kind=summary["metric_kind"],
        sampling_seconds=summary["sampling_seconds"], valid_range=summary["valid_range"], roles=roles)
    label_bytes = canonical(role_labels).encode()
    (root / "trusted/labels.json").write_bytes(label_bytes)
    (root / "trusted/experiment.json").write_text(canonical({"schema_version": "metrics-normalized-input/1",
        "origin": "uploaded_csv", "dataset": manifest.model_dump(mode="json"), "labels_sha256": digest(label_bytes),
        "labels_available": flags is not None, "label_source": label_source if flags is not None else None,
        "split": summary["splits"], "prefix_policy": "labels false in unscored warmup; no assumption about warmup anomalies",
        "selection_policy": summary["selection_policy"]}))
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    (root / "upload.json").write_text(canonical(summary))
    return summary


def load_upload(root):
    path = Path(root) / "upload.json"
    if not path.exists():
        return None
    summary = json.loads(path.read_bytes())
    if digest((Path(root) / "observations.csv").read_bytes()) != summary["sha256"]:
        raise ValueError("upload observation digest mismatch")
    return summary


def detection_result(points, scores, *, manifest, prefix, threshold, persistence, elapsed, labels=None):
    from contracts.metrics import EvaluationPolicy
    from factory.metrics.evaluation import evaluate
    if labels is not None:
        return evaluate(points, scores, [False]*prefix + labels, host_id=manifest.host_id, metric=manifest.metric,
            sampling_seconds=manifest.sampling_seconds, prefix_points=prefix, threshold=threshold,
            elapsed_seconds=elapsed, policy=EvaluationPolicy(persistence_points=persistence))
    # Reuse trusted alarm/event semantics without inventing normal labels.
    flags = alarms(scores[prefix:], threshold=threshold, persistence_points=persistence)
    coverage = sum(s.status == "ok" for s in scores[prefix:])/len(flags)
    return {"execution_status": "SUCCEEDED", "effect_status": "NOT_EVALUATED", "acceptance_status": "NOT_EVALUATED",
            "engineering_status": "PASSED" if coverage >= .95 else "COVERAGE_FAILED", "notice": UNKNOWN,
            "coverage": {"value": coverage},
            "runtime_seconds": elapsed, "peak_memory_bytes": None, "peak_memory_null_reason": "not_measured",
            "predicted_events": [e.model_dump(mode="json") for e in events_from_flags(points[prefix:], flags,
                metric=manifest.metric, sampling_seconds=manifest.sampling_seconds, id_prefix="pred")]}


def save_curve(directory, name, *, points, scores, prefix, threshold, candidate, version, source,
               manifest, result, task_id, labels=None, reference_points=None):
    """Persist exact observations/outputs, including prefix. Rendering never calls a detector."""
    prep, rows = CausalPreprocessor(), []
    flags = [False]*prefix + alarms(scores[prefix:], threshold=threshold, persistence_points=candidate.persistence_points)
    for i, (point, score) in enumerate(zip(points, scores)):
        processed = prep.step(point)
        rows.append({"timestamp": point.timestamp.isoformat(), "value": point.value, "host_id": point.host_id,
            "processed_value": processed.value, "imputation": processed.imputation, "status": score.status,
            "score": score.score, "evidence": score.evidence, "prediction": flags[i], "role": "warmup" if i < prefix else "detection",
            "task_id": task_id, "candidate_id": candidate.candidate_id, "version": version, "data_source": source["type"]})
    payload = {"task_id": task_id, "source": source, "candidate_id": candidate.candidate_id, "version": version,
        "config": candidate.config.model_dump(mode="json"), "threshold": threshold, "unit": manifest.unit,
        "sampling_seconds": manifest.sampling_seconds, "rows": rows, "result": result}
    if labels is not None:
        for row, label in zip(rows[prefix:], labels):
            row["label"] = label
    if reference_points is not None:
        earlier = reference_points[:len(reference_points)-prefix]
        history_rows = [{**rows[0], "timestamp": point.timestamp.isoformat(), "value": point.value,
            "processed_value": None, "imputation": "not_scored", "status": "historical_reference_not_scored", "score": None,
            "evidence": {}, "prediction": False, "role": "fit_history" if i < source["fit_points"] else "calibration_history"}
            for i, point in enumerate(earlier)]
        rows = history_rows + rows
        payload["rows"] = rows
    content = canonical(payload).encode()
    (Path(directory) / f"{name}-curve.json").write_bytes(content)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]) + (["label"] if labels is not None and "label" not in rows[0] else []))
    writer.writeheader()
    writer.writerows({**row, "evidence": canonical(row["evidence"])} for row in rows)
    (Path(directory) / f"{name}-points.csv").write_text(output.getvalue())
    (Path(directory) / f"{name}-events.json").write_text(canonical({"task_id": task_id, "candidate_id": candidate.candidate_id,
        "version": version, "source": source, "predicted_events": result.get("predicted_events", []),
        "truth_events": result.get("truth_events"), "matching": result.get("event")}))
    return {"path": f"{name}-curve.json", "sha256": digest(content),
        "downloads": {f"{name}-{suffix}": digest((Path(directory) / f"{name}-{suffix}").read_bytes()) for suffix in ("points.csv", "events.json")}}
