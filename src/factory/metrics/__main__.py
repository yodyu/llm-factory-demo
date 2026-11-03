"""Stage-one trusted tools. These commands do not generate or execute candidate code."""
from factory.metrics.capability_registry import methods, default_methods, configuration, needs_calibration

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from contracts.base import strict_json_loads
from contracts.metrics import EvaluationPolicy, MetricsDataset
from factory.metrics.data import CausalPreprocessor, load_role
from factory.metrics.evaluation import calibrate, evaluate, select_development
from factory.metrics.reference import create_detector
from factory.metrics.synthetic import SCENARIOS, generate, write_dataset
from factory.runtime.artifacts import digest


def reference_check(dataset_root: Path, *, threshold: float) -> dict:
    """Development-only framework check, explicitly distinct from generated candidates."""
    raw = (dataset_root / "manifest.json").read_bytes()
    manifest = MetricsDataset.model_validate(strict_json_loads(raw))
    train = load_role(dataset_root, manifest, "train")
    calibration = load_role(dataset_root, manifest, "calibration")
    development = load_role(dataset_root, manifest, "development")
    experiment = strict_json_loads((dataset_root / "trusted" / "experiment.json").read_bytes())
    label_bytes = (dataset_root / "trusted" / "labels.json").read_bytes()
    if (digest(label_bytes) != experiment["labels_sha256"]
            or experiment["dataset"] != manifest.model_dump(mode="json")):
        raise ValueError("experiment/label binding mismatch")
    # Only trusted code loads labels; there is no model/worker in this reference tool.
    labels = strict_json_loads(label_bytes)["development"]
    policy = EvaluationPolicy()
    records = []
    for config in [configuration(method, {"threshold": threshold}) for method in default_methods()]:
        detector = create_detector(config)
        detector.fit(train)

        def run_role(points, prefix):
            detector.reset()
            prep, scores, started = CausalPreprocessor(), [], None
            for index, point in enumerate(points):
                if index == prefix:
                    started = time.monotonic()
                scores.append(detector.score_one(prep.step(point)))
            return scores, time.monotonic() - started

        frozen_threshold = 0.0
        calibration_record = {"rule": "fixed_parameter_unchanged", "labels_used": False}
        if needs_calibration(config):
            cal_prefix = manifest.roles["calibration"].prefix_points
            scores, _ = run_role(calibration, cal_prefix)
            calibration_record = calibrate(scores, quantile=config.quantile, prefix_points=cal_prefix)
            frozen_threshold = calibration_record["threshold"]
        prefix = manifest.roles["development"].prefix_points
        scores, elapsed = run_role(development, prefix)
        result = evaluate(development, scores, labels, host_id=manifest.host_id, metric=manifest.metric,
                          sampling_seconds=manifest.sampling_seconds, prefix_points=prefix,
                          threshold=frozen_threshold, elapsed_seconds=elapsed, policy=policy)
        records.append({"candidate_id": config.method_id, "origin": "reference", "role": "development",
                        "config": config.model_dump(mode="json"), "calibration": calibration_record,
                        "report": result})
    return {"schema_version": "metrics-reference-check/1", "origin": "reference",
            "dataset_id": manifest.dataset_id, "manifest_sha256": digest(raw),
            "label_sha256": digest(label_bytes), "policy": policy.model_dump(mode="json"),
            "threshold_source": "command_line_unconfirmed_business_parameter",
            "runtime_scope": "scoring_loop_only_including_preprocessing_and_output_collection",
            # This reference-only command has no frozen user task or preferences.
            "candidates": records, "selection": select_development(records, objective="event_detection", policy="balanced"),
            "final_test_executed": False, "model_calls": 0,
            "limitations": ["human references only; not LLM generation or sandbox validation",
                            "synthetic data; no business acceptance threshold defined"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sim = commands.add_parser("simulate", help="write a new trusted four-role synthetic dataset")
    sim.add_argument("--scenario", choices=SCENARIOS, required=True)
    sim.add_argument("--output", type=Path, required=True)
    sim.add_argument("--seed", type=int, default=20261031)
    ref = commands.add_parser("reference-check", help="development-only human-reference framework check")
    ref.add_argument("--dataset", type=Path, required=True)
    ref.add_argument("--threshold", type=float, required=True)
    ref.add_argument("--output", type=Path, required=True)
    sandbox = commands.add_parser("sandbox-check", help="method checks for an explicitly identified source")
    sandbox.add_argument("--source", type=Path, required=True)
    sandbox.add_argument("--method", choices=methods(), required=True)
    sandbox.add_argument("--threshold", type=float, default=85.0)
    sandbox.add_argument("--origin", choices=["reference", "mock", "llm_api", "fault_injection", "historical"], required=True)
    sandbox.add_argument("--image", required=True, help="approved full sha256 image ID")
    sandbox.add_argument("--state", type=Path, required=True)
    sandbox.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "simulate":
        write_dataset(args.output, generate(args.scenario, seed=args.seed))
        print(json.dumps({"dataset": str(args.output), "origin": "synthetic_injection"}))
    elif args.command == "reference-check":
        result = reference_check(args.dataset, threshold=args.threshold)
        with args.output.open("x") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"report": str(args.output), "origin": "reference",
                          "selection": result["selection"], "final_test_executed": False}))
    else:
        from contracts.metrics import MetricsTask
        from execution.metrics_runner import MetricsRunner
        from factory.metrics.runtime import MetricsStore
        from factory.metrics.validation import validate_candidate

        if args.output.exists():
            raise FileExistsError(args.output)
        store = MetricsStore(args.state / "metrics.sqlite")
        task_id = "method-check-" + uuid4().hex[:16]
        store.create_task(MetricsTask(task_id=task_id, requirement="人工指定源码的方法语义检查",
                          dataset_id="method-validation", metric="numeric", anomaly_target="method_semantics",
                          explicit_constraints={}, ranking_preferences=[], allowed_methods=[args.method],
                          knowledge_snapshot=digest(b"{}"), model_mode="mock", model_profile_id="no-model-calls"))
        runner = MetricsRunner(store, store.artifact_store, args.state / "packages", args.state / "work", image=args.image)
        config = configuration(args.method, {"threshold": args.threshold})
        source = args.source.read_text()
        operation_id = task_id + ":method-check"
        store.reserve(task_id, "metrics-code", operation_id, digest(source.encode()))
        store.mark_operation(operation_id, "SENT")
        try:
            result = validate_candidate(runner, task_id, source, config, candidate_id=args.method, version=0, origin=args.origin)
            reference = store.register_document(task_id, result, "method-validation")
            store.mark_operation(operation_id, "SUCCEEDED" if result["passed"] else "FAILED", reference)
            result.update({"task_id": task_id, "validation_ref": reference, "image_id": args.image,
                           "model_calls": 0, "final_test_executed": False,
                           "origin_asserted_by": "cli_operator", "generation_evidence_verified": False})
            with args.output.open("x") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            print(json.dumps({"report": str(args.output), "passed": result["passed"], "origin": args.origin}))
            return 0 if result["passed"] else 2
        finally:
            runner.cleanup_orphans()


if __name__ == "__main__":
    raise SystemExit(main())
