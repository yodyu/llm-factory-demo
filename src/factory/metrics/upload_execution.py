"""Frozen upload scoring and isolated benchmark evaluation. Deliberately no gateway."""
from factory.metrics.capability_registry import needs_calibration
from pathlib import Path

from contracts.base import strict_json_loads
from contracts.metrics import CandidatePlan, MetricsDataset
from factory.metrics.data import load_role
from factory.metrics.evaluation import calibrate
from factory.metrics.upload import BENCHMARK_NOTICE, detection_result, label_flags, load_upload, save_curve
from factory.runtime.artifacts import digest


def final_upload(store, runner, task_id, root, directory, freeze, selection_hash, manifest, source):
    from factory.metrics.workflow import execute, role_scores, decode_scores, failure
    if digest((root / "upload.json").read_bytes()) != freeze["bindings"]["upload_sha256"]:
        raise ValueError("frozen upload configuration changed")
    upload = load_upload(root)
    candidate = CandidatePlan.model_validate(freeze["plan"])
    train = load_role(root, manifest, "train")
    points = load_role(root, manifest, "test")
    prefix = manifest.roles["test"].prefix_points
    curves = {}
    try:
        scored = execute(store, task_id, "uploaded-detection", freeze,
            lambda: role_scores(runner, task_id, source, candidate.config, train, points, prefix))
        labels = None
        if upload["labels"] is not None:
            raw_labels = (root / "trusted" / "user-labels.csv").read_bytes()
            if digest(raw_labels) != upload["labels"]["sha256"]:
                raise ValueError("user label binding mismatch")
            labels = label_flags(raw_labels, points[prefix:], manifest.host_id)
        result = detection_result(points, decode_scores(scored), manifest=manifest, prefix=prefix,
            threshold=freeze["threshold"], persistence=candidate.persistence_points, elapsed=scored["elapsed_seconds"], labels=labels)
        result.update({"threshold": freeze["threshold"], "config": freeze["plan"]["config"],
            "labels": upload["labels"], "selection_sha256": selection_hash, "selected": candidate.candidate_id,
            "phase": "uploaded_detection", "test_execution_started": True})
        curves["detection"] = save_curve(directory, "detection", points=points, scores=decode_scores(scored), prefix=prefix,
            threshold=freeze["threshold"], candidate=candidate, version=Path(freeze["source_path"]).stem,
            source=upload, manifest=manifest, result=result, task_id=task_id, labels=labels,
            reference_points=load_role(root, manifest, "development"))
    except Exception as error:
        result = {"execution_status": "FAILED", "effect_status": "NOT_EVALUATED", "failure": failure(error), "test_execution_started": True}
    benchmark = evaluate_benchmark(store, runner, task_id, root, directory, freeze, selection_hash, source, upload, candidate, curves)
    return {**result, "curves": curves, "independent_benchmark": benchmark}


def evaluate_benchmark(store, runner, task_id, root, directory, freeze, selection_hash, source, upload, candidate, curves):
    """Optional post-selection diagnostic; never participates in either source's ranking."""
    from factory.metrics.workflow import execute, role_scores, decode_scores, failure, trusted_labels
    benchmark = {**upload["benchmark"], "notice": BENCHMARK_NOTICE, "execution_status": "NOT_APPLICABLE"}
    if upload["benchmark"]["status"] == "READY":
        try:
            base = root / "benchmark"
            raw = (base / "manifest.json").read_bytes()
            if digest(raw) != upload["benchmark"]["manifest_sha256"] or digest((base / "trusted" / "experiment.json").read_bytes()) != upload["benchmark"]["experiment_sha256"]:
                raise ValueError("frozen benchmark changed")
            bm = MetricsDataset.model_validate(strict_json_loads(raw))
            bm_train = load_role(base, bm, "train")
            bm_cal = load_role(base, bm, "calibration")
            binding = {"selection_sha256": selection_hash, "manifest_sha256": digest(raw), "source_sha256": freeze["source_sha256"],
                "config": candidate.config.model_dump(mode="json"), "roles": {k: v.model_dump(mode="json") for k, v in bm.roles.items()},
                "state_policy": "fresh independent detector for calibration and test; independent of upload fitted state"}
            calibration = {"threshold": 0.0, "rule": "fixed_parameter_unchanged", "labels_used": False}
            if needs_calibration(candidate.config):
                cal_prefix = bm.roles["calibration"].prefix_points
                scored = execute(store, task_id, "benchmark-calibration", binding,
                    lambda: role_scores(runner, task_id, source, candidate.config, bm_train, bm_cal, cal_prefix))
                calibration = calibrate(decode_scores(scored), quantile=candidate.config.quantile, prefix_points=cal_prefix)
            calibration["binding"] = binding
            test = load_role(base, bm, "test")
            bp = bm.roles["test"].prefix_points
            labels, _ = trusted_labels(base, bm, "test")
            scored = execute(store, task_id, "independent-benchmark-test", binding,
                lambda: role_scores(runner, task_id, source, candidate.config, bm_train, test, bp))
            measured = detection_result(test, decode_scores(scored), manifest=bm, prefix=bp, threshold=calibration["threshold"],
                persistence=candidate.persistence_points, elapsed=scored["elapsed_seconds"], labels=labels[bp:])
            benchmark.update({"execution_status": "SUCCEEDED", "evaluation": measured, "calibration": calibration,
                "threshold": calibration["threshold"], "config": binding["config"], "binding": binding})
            curves["benchmark"] = save_curve(directory, "benchmark", points=test, scores=decode_scores(scored), prefix=bp,
                threshold=calibration["threshold"], candidate=candidate, version=Path(freeze["source_path"]).stem,
                source={"type": "independent_benchmark", "display_name": bm.dataset_id, "metric": bm.metric},
                manifest=bm, result=measured, task_id=task_id, labels=labels[bp:])
        except Exception as error:
            benchmark.update({"execution_status": "FAILED", "effect_status": "NOT_EVALUATED", "failure": failure(error)})
    return benchmark
