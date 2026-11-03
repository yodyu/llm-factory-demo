"""New evaluation of frozen last candidate versions after a validator correction.

No model, code repair or parameter change occurs. Original reports remain
immutable. Test reuse is explicitly disclosed and is not a fresh holdout claim.
"""
from factory.metrics.capability_registry import needs_calibration

from pathlib import Path
from uuid import uuid4

from contracts.metrics import CandidatePlan, EvaluationPolicy, MetricsDataset, MetricsTask
from contracts.base import strict_json_loads
from execution.metrics_runner import MetricsRunner, DEPENDENCY_PROFILE
from factory.metrics.data import load_role
from factory.metrics.evaluation import calibrate, evaluate, select_development
from factory.metrics.knowledge import canonical, identity
from factory.metrics.reports import bound_report, markdown
from factory.metrics.runtime import MetricsStore
from factory.metrics.validation import validate_candidate
from factory.metrics.workflow import decode_scores, execute, failure, final_evaluate, role_scores, trusted_labels, write_json
from factory.runtime.artifacts import digest


def requalify(source_store, source_directory, dataset_root, *, state, image, knowledge):
    source_directory, dataset_root, state = Path(source_directory), Path(dataset_root), Path(state)
    original = bound_report(source_store, source_directory)
    raw = (dataset_root / "manifest.json").read_bytes()
    if digest(raw) != original["bindings"]["manifest_sha256"]:
        raise ValueError("requalification dataset differs from frozen input")
    dataset = MetricsDataset.model_validate(strict_json_loads(raw))
    task_id = "requalify-" + uuid4().hex[:16]
    values = {**original["task"], "task_id": task_id, "model_profile_id": "recorded-no-model"}
    values["budgets"] = {**values["budgets"], "model_calls": 0, "repair_rounds": 0}
    task = MetricsTask.model_validate(values)
    store = MetricsStore(state / "runtime.sqlite")
    store.create_task(task)
    directory = state / "runs" / identity("task", task_id)
    directory.mkdir(parents=True, exist_ok=False)
    runner = MetricsRunner(store, store.artifact_store, state / "packages", directory / "sandbox", image=image)
    report = {"schema_version": "metrics-run/1", "task": task.model_dump(mode="json"), "origin": "historical",
              "original_origin": original["origin"], "source_task_id": original["task"]["task_id"],
              "source_report_sha256": digest((source_directory / "report.json").read_bytes()),
              "knowledge_snapshot": original["knowledge_snapshot"], "retrieval_mode": "recorded_no_new_retrieval",
              "dataset_public": original["dataset_public"], "bindings": dict(original["bindings"]),
              "dependency_profile": DEPENDENCY_PROFILE, "candidates": [], "model_operations": [],
              "model_calls": 0, "campaign_budget": None, "status": "RUNNING", "final_test_executed": False,
              "qualification_protocol": "metrics-method-check/3",
              "prior_test_exposure": original.get("final_test_executed", False),
              "limitations": ["frozen last available source only; no model generation or repair",
                              "original trial used a defective stability comparator; do not claim clean retrieval benefit",
                              "previously tested data, when applicable, is disclosed; no fresh generalization claim"]}
    try:
        train = load_role(dataset_root, dataset, "train")
        calibration = load_role(dataset_root, dataset, "calibration")
        development = load_role(dataset_root, dataset, "development")
        labels, label_hash = trusted_labels(dataset_root, dataset, "development")
        if label_hash != report["bindings"]["labels_sha256"]:
            raise ValueError("requalification label binding mismatch")
        report["bindings"]["image_id"] = image
        write_json(directory / "task.json", report["task"])
        write_json(directory / "knowledge.json", report["knowledge_snapshot"])
        write_json(directory / "dataset-manifest.json", dataset.model_dump(mode="json"))
        store.phase(task_id, "DATA_READY", report["bindings"])
        store.phase(task_id, "KNOWLEDGE_READY", {"snapshot_id": task.knowledge_snapshot})
        store.phase(task_id, "PLANNED", {"original_task_id": report["source_task_id"], "policy": "original frozen plans"})
        store.phase(task_id, "VALIDATING", {"protocol": "metrics-method-check/3"})
        for old in original["candidates"]:
            plan = CandidatePlan.model_validate(old["plan"])
            candidate = {"candidate_id": plan.candidate_id, "role": "development", "plan": old["plan"], "versions": []}
            report["candidates"].append(candidate)
            try:
                if not old["versions"]:
                    raise ValueError("NO_RECORDED_SOURCE")
                previous = old["versions"][-1]
                source = (source_directory / previous["source_path"]).read_bytes()
                if digest(source) != previous["source_sha256"]:
                    raise ValueError("recorded source digest mismatch")
                folder = directory / identity("candidate", plan.candidate_id)
                folder.mkdir()
                (folder / "recorded.py").write_bytes(source)
                ref = store.artifact_store.put(source)
                store.attach_artifact(task_id, ref, len(source), "candidate-source")
                version = {"version": previous["version"], "origin": previous["origin"], "source_sha256": ref, "source_ref": ref,
                           "source_path": str((folder / "recorded.py").relative_to(directory)),
                           "explanation": "unchanged last source from original model task", "knowledge_ids": previous["knowledge_ids"]}
                candidate["versions"].append(version)
                checks = execute(store, task_id, "check-" + plan.candidate_id, {"source": ref, "config": old["plan"]},
                                 lambda: validate_candidate(runner, task_id, source.decode(), plan.config,
                                          candidate_id=plan.candidate_id, version=previous["version"], origin="historical"))
                version["validation"] = checks
                write_json(folder / "recorded-checks.json", checks)
                if not checks["passed"]:
                    raise ValueError("METHOD_CHECK_V2_FAILED")
                calibration_record = {"threshold": 0.0, "rule": "fixed_parameter_unchanged", "labels_used": False}
                if needs_calibration(plan.config):
                    prefix = dataset.roles["calibration"].prefix_points
                    scored = execute(store, task_id, "calibration-" + plan.candidate_id, {"source": ref, "bindings": report["bindings"]},
                                     lambda: role_scores(runner, task_id, source.decode(), plan.config, train, calibration, prefix))
                    calibration_record = calibrate(decode_scores(scored), quantile=plan.config.quantile, prefix_points=prefix)
                candidate["calibration"] = calibration_record
                prefix = dataset.roles["development"].prefix_points
                scored = execute(store, task_id, "development-" + plan.candidate_id, {"source": ref, "bindings": report["bindings"]},
                                 lambda: role_scores(runner, task_id, source.decode(), plan.config, train, development, prefix))
                candidate["report"] = evaluate(development, decode_scores(scored), labels, host_id=dataset.host_id,
                      metric=dataset.metric, sampling_seconds=dataset.sampling_seconds, prefix_points=prefix,
                      threshold=calibration_record["threshold"], elapsed_seconds=scored["elapsed_seconds"],
                      policy=EvaluationPolicy(persistence_points=plan.persistence_points))
            except Exception as error:
                candidate["failure"] = failure(error)
                candidate["report"] = {"execution_status": "FAILED", "engineering_status": "FAILED", "effect_status": "NOT_MEASURED"}
        selection = select_development(report["candidates"], objective=task.evaluation_objective,
                                       policy=task.selection_policy, acceptance=task.acceptance_criteria,
                                       candidate_limit=task.budgets.candidates)
        report["selection"] = selection
        if selection["selected"] is None:
            raise ValueError(selection["status"])
        selected = next(c for c in report["candidates"] if c["candidate_id"] == selection["selected"])
        freeze = {"task_sha256": store.task(task_id)["spec_hash"], "bindings": report["bindings"],
                  "selected": selected["candidate_id"], "plan": selected["plan"], "source_path": selected["versions"][-1]["source_path"],
                  "source_sha256": selected["versions"][-1]["source_sha256"], "threshold": selected["calibration"]["threshold"],
                  "selection": selection, "protocol": task.validation_protocol, "source_report_sha256": report["source_report_sha256"]}
        freeze["selection_sha256"] = digest(canonical(freeze).encode())
        write_json(directory / "selection.json", freeze)
        store.phase(task_id, "SELECTED", freeze)
        report["final"] = final_evaluate(store, runner, task_id, dataset_root, directory)
        report["final_test_executed"] = report["final"].get("test_execution_started", False)
        report["final_evaluation_attempted"] = True
        store.phase(task_id, "FINAL_EVALUATED", report["final"])
        report["status"] = "COMPLETED" if report["final"]["execution_status"] == "SUCCEEDED" else "FAILED"
        store.phase(task_id, report["status"], {"final": report["final"], "origin": "historical"})
    except Exception as error:
        report.update({"status": "FAILED", "failure": failure(error)})
        if store.task(task_id)["phase"] not in {"FAILED", "COMPLETED"}:
            store.phase(task_id, "FAILED", report["failure"])
    finally:
        runner.cleanup_orphans()
    write_json(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report))
    store.register_document(task_id, report, "run-report")
    from factory.metrics.publication import publish_pending
    receipt = publish_pending(store, knowledge, report)
    write_json(directory / "publication.json", receipt)
    return {"task_id": task_id, "source_task_id": report["source_task_id"], "directory": str(directory),
            "status": report["status"], "model_calls": 0, "prior_test_exposure": report["prior_test_exposure"]}
