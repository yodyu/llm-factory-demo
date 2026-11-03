"""Trusted execution primitives shared by graph orchestration and historical replay."""

import json
import time
from pathlib import Path

from contracts import ErrorCode, FactoryError
from contracts.base import strict_json_loads
from contracts.metrics import MetricsDataset
from execution.metrics_runner import CandidateFailure
from factory.metrics.data import CausalPreprocessor, load_role
from factory.metrics.knowledge import canonical
from factory.runtime.artifacts import digest
from factory.metrics.upload import load_upload, save_curve


def write_json(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def failure(error):
    if isinstance(error, CandidateFailure):
        return {"code": "CANDIDATE_ERROR", "feedback": error.feedback}
    if isinstance(error, FactoryError):
        return {"code": error.code.value, "message": str(error)}
    # Inputs are numeric/allowlisted. Do not persist arbitrary provider exceptions.
    return {"code": type(error).__name__, "message": str(error)[:500] if isinstance(error, ValueError) else "internal failure; inspect trusted server logs"}


def execute(store, task_id, stage, inputs, action):
    op = task_id + ":" + stage
    reserved = store.reserve(task_id, "metrics-code", op, digest(canonical(inputs).encode()))
    if not reserved["is_new"]:
        raise FactoryError(ErrorCode.INPUT_CONFLICT, "execution already reserved; automatic replay is forbidden")
    store.mark_operation(op, "SENT")
    try:
        result = action()
        ref = store.register_document(task_id, result, stage)
        store.mark_operation(op, "SUCCEEDED", ref)
        return result
    except Exception as error:
        ref = store.register_document(task_id, failure(error), stage + "-failure")
        store.mark_operation(op, "FAILED", ref)
        raise


def role_scores(runner, task_id, source, config, train, points, prefix):
    with runner.detector(task_id, source, point_count=len(points), fit_count=len(train)) as detector:
        detector.fit(config, train)
        detector.reset()
        prep, scores, started = CausalPreprocessor(), [], None
        for index, point in enumerate(points):
            if index == prefix:
                started = time.monotonic()
            scores.append(detector.score_one(prep.step(point)))
        elapsed = time.monotonic() - started
    return {"scores": [score.model_dump(mode="json") for score in scores], "elapsed_seconds": elapsed}


def decode_scores(result):
    from contracts.metrics import Score
    return [Score.model_validate(point) for point in result["scores"]]


def trusted_labels(root, manifest, role):
    experiment = strict_json_loads((root / "trusted" / "experiment.json").read_bytes())
    labels = (root / "trusted" / "labels.json").read_bytes()
    if experiment["dataset"] != manifest.model_dump(mode="json") or digest(labels) != experiment["labels_sha256"]:
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "trusted label/experiment binding mismatch")
    return strict_json_loads(labels)[role], digest(labels)


FAULT = '''
# Deliberate test-only fault injection: do not count as a natural model failure.
_fault_original_factory = create_detector
def create_detector(config):
    original = _fault_original_factory(config)
    class FaultProxy:
        def fit(self, points): return original.fit(points)
        def reset(self): return original.reset()
        def save_state(self): return original.save_state()
        def load_state(self, raw): return original.load_state(raw)
        def score_one(self, point):
            result = original.score_one(point)
            if result['status'] == 'ok': result['score'] += 1.0
            return result
    return FaultProxy()
'''


def final_evaluate(store, runner, task_id, dataset_root, directory, *, role_loader=None):
    if store.task(task_id)["phase"] != "SELECTED":
        raise FactoryError(ErrorCode.INVALID_INPUT, "final evaluation requires immutable selection")
    freeze = strict_json_loads((directory / "selection.json").read_bytes())
    expected = freeze.pop("selection_sha256")
    if digest(canonical(freeze).encode()) != expected:
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "selection digest mismatch")
    # Check against the ledger, not merely the mutable sidecar file hash.
    with store._transaction() as db:
        row = db.execute("SELECT evidence_ref FROM phase_history WHERE task_id=? AND phase='SELECTED'", (task_id,)).fetchone()
    if store.document(row[0]) != {**freeze, "selection_sha256": expected}:
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "selection differs from frozen ledger evidence")
    raw = (dataset_root / "manifest.json").read_bytes()
    source = (directory / freeze["source_path"]).read_bytes()
    if (digest(raw) != freeze["bindings"]["manifest_sha256"] or digest(source) != freeze["source_sha256"]
            or freeze["task_sha256"] != store.task(task_id)["spec_hash"]):
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "final input/code/task binding mismatch")
    manifest = MetricsDataset.model_validate(strict_json_loads(raw))
    upload = load_upload(dataset_root)
    if upload and digest((dataset_root / "upload.json").read_bytes()) != freeze["bindings"]["upload_sha256"]:
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "upload configuration changed")
    if upload and upload.get("pipeline") != "four-role-comparison/1":
        from factory.metrics.upload_execution import final_upload
        return final_upload(store, runner, task_id, dataset_root, directory, freeze, expected, manifest, source.decode())
    labels, label_hash = trusted_labels(dataset_root, manifest, "test")
    if label_hash != freeze["bindings"]["labels_sha256"]:
        raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "final label binding mismatch")
    from contracts.metrics import CandidatePlan
    candidate = CandidatePlan.model_validate(freeze["plan"])
    # Test file is first read here, after ledger selection is frozen.
    execution_started = False
    try:
        loader = role_loader or load_role
        train = loader(dataset_root, manifest, "train")
        test = loader(dataset_root, manifest, "test")
        prefix = manifest.roles["test"].prefix_points
        execution_started = True
        scored = execute(store, task_id, "final-test", {**freeze, "selection_sha256": expected},
                         lambda: role_scores(runner, task_id, source.decode(), candidate.config, train, test, prefix))
        from factory.metrics.upload import detection_result
        result = detection_result(test, decode_scores(scored), manifest=manifest, prefix=prefix, threshold=freeze["threshold"],
                                  elapsed=scored["elapsed_seconds"], persistence=candidate.persistence_points,
                                  labels=labels[prefix:] if labels is not None else None)
        source_info = upload or {"type": "builtin_simulation", "display_name": manifest.dataset_id, "metric": manifest.metric}
        if upload:
            result["labels"] = upload["labels"]
        curve = save_curve(directory, "detection", points=test, scores=decode_scores(scored), prefix=prefix,
            threshold=freeze["threshold"], candidate=candidate, version=Path(freeze["source_path"]).stem,
            source=source_info, manifest=manifest, result=result, task_id=task_id,
            labels=labels[prefix:] if labels is not None else None)
        curves = {"detection": curve}
        final = {**result, "curves": curves, "selection_sha256": expected, "selected": candidate.candidate_id,
                 "phase": "test", "test_execution_started": True}
        if upload:
            from factory.metrics.upload_execution import evaluate_benchmark
            final["independent_benchmark"] = evaluate_benchmark(store, runner, task_id, dataset_root, directory,
                freeze, expected, source.decode(), upload, candidate, curves)
        return final
    except Exception as error:
        return {"execution_status": "FAILED", "effect_status": "NOT_MEASURED", "failure": failure(error),
                "selected": candidate.candidate_id, "selection_sha256": expected, "phase": "test", "test_execution_started": execution_started,
                "policy": "terminal; no repair, retuning or candidate reselection"}
