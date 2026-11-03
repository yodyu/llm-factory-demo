"""Zero-model replay of an exported recorded winner, with archive and ledger binding."""
from factory.metrics.capability_registry import needs_calibration

import math
import zipfile
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from contracts.base import RelativePath, strict_json_loads
from contracts.metrics import CandidatePlan, MetricsDataset, MetricsTask
from execution.metrics_runner import MetricsRunner
from factory.metrics.data import load_role
from factory.metrics.evaluation import calibrate
from factory.metrics.knowledge import canonical, verify_snapshot
from factory.metrics.runtime import MetricsStore
from factory.metrics.validation import validate_candidate
from factory.metrics.workflow import decode_scores, execute, failure, final_evaluate, role_scores, write_json
from factory.runtime.artifacts import digest


def replay_bundle(bundle, expected_sha256, *, state, image):
    bundle, state = Path(bundle), Path(state)
    if digest(bundle.read_bytes()) != expected_sha256:
        raise ValueError("recorded archive digest mismatch")
    task_id = "replay-" + uuid4().hex[:16]
    directory = state / task_id
    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        if (len(entries) != len({i.filename for i in entries}) or len(entries) > 5000
                or sum(i.file_size for i in entries) > 64 * 1024 * 1024):
            raise ValueError("invalid or oversized recorded archive")
        manifest = strict_json_loads(archive.read("bundle-manifest.json"))
        if set(archive.namelist()) != set(manifest["files"]) | {"bundle-manifest.json"}:
            raise ValueError("archive file whitelist mismatch")
        for name, entry in manifest["files"].items():
            TypeAdapter(RelativePath).validate_python(name)
            raw = archive.read(name)
            if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
                raise ValueError("recorded file digest mismatch")
            path = directory / "input" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    root = directory / "input"
    report = strict_json_loads((root / "report.json").read_bytes())
    old_selection = strict_json_loads((root / "selection.json").read_bytes())
    old_hash = old_selection.pop("selection_sha256")
    if digest(canonical(old_selection).encode()) != old_hash:
        raise ValueError("recorded selection digest mismatch")
    snapshot = verify_snapshot(strict_json_loads((root / "knowledge.json").read_bytes()))
    if snapshot["snapshot_id"] != old_selection["bindings"]["knowledge_snapshot"]:
        raise ValueError("recorded knowledge binding mismatch")
    plan = CandidatePlan.model_validate(old_selection["plan"])
    TypeAdapter(RelativePath).validate_python(old_selection["source_path"])
    source = (root / old_selection["source_path"]).read_bytes()
    if digest(source) != old_selection["source_sha256"]:
        raise ValueError("recorded source binding mismatch")
    dataset_root = root / "dataset"
    raw = (dataset_root / "manifest.json").read_bytes()
    if digest(raw) != old_selection["bindings"]["manifest_sha256"]:
        raise ValueError("recorded dataset binding mismatch")
    dataset = MetricsDataset.model_validate(strict_json_loads(raw))
    task_values = {**report["task"], "task_id": task_id, "model_profile_id": "recorded-no-model"}
    task_values["budgets"] = {**task_values["budgets"], "model_calls": 0, "repair_rounds": 0}
    task = MetricsTask.model_validate(task_values)
    store = MetricsStore(state / "runtime.sqlite")
    store.create_task(task)
    runner = MetricsRunner(store, store.artifact_store, state / "packages", directory / "sandbox", image=image)
    result = {"schema_version": "metrics-recorded-replay/1", "origin": "historical", "original_origin": report["origin"],
              "original_task_id": report["task"]["task_id"], "task_id": task_id, "model_calls": 0,
              "bundle_sha256": expected_sha256, "policy": "recorded winner only; no generation, repair or reselection"}
    try:
        store.phase(task_id, "DATA_READY", old_selection["bindings"])
        store.phase(task_id, "KNOWLEDGE_READY", {"snapshot_id": snapshot["snapshot_id"]})
        store.phase(task_id, "PLANNED", {"recorded_plan": plan.model_dump(mode="json")})
        store.phase(task_id, "VALIDATING", {"origin": "historical"})
        checks = execute(store, task_id, "recorded-method-check", {"source_sha256": digest(source), "image": image},
                         lambda: validate_candidate(runner, task_id, source.decode(), plan.config,
                                  candidate_id=plan.candidate_id, version=0, origin="historical", protocol="metrics-method-check/2"))
        result["method_checks"] = checks
        if not checks["passed"]:
            raise ValueError("recorded source no longer passes method checks")
        if needs_calibration(plan.config):
            train = load_role(dataset_root, dataset, "train")
            calibration = load_role(dataset_root, dataset, "calibration")
            prefix = dataset.roles["calibration"].prefix_points
            scores = execute(store, task_id, "recorded-calibration", {"source_sha256": digest(source), "data": dataset.roles["calibration"].sha256},
                             lambda: role_scores(runner, task_id, source.decode(), plan.config, train, calibration, prefix))
            measured = calibrate(decode_scores(scores), quantile=plan.config.quantile, prefix_points=prefix)
            if not math.isclose(measured["threshold"], old_selection["threshold"], rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError("recorded calibration no longer matches; no retuning allowed")
        (directory / "selected.py").write_bytes(source)
        freeze = {**old_selection, "task_sha256": store.task(task_id)["spec_hash"], "source_path": "selected.py",
                  "recorded_bundle_sha256": expected_sha256}
        freeze["selection_sha256"] = digest(canonical(freeze).encode())
        write_json(directory / "selection.json", freeze)
        store.phase(task_id, "SELECTED", freeze)
        final = final_evaluate(store, runner, task_id, dataset_root, directory)
        result["final"] = final
        store.phase(task_id, "FINAL_EVALUATED", final)
        if final["execution_status"] == "SUCCEEDED":
            result["status"] = "COMPLETED"
            store.phase(task_id, "COMPLETED", {"origin": "historical", "model_calls": 0})
        else:
            result["status"] = "FAILED"
            store.phase(task_id, "FAILED", final)
        original = report.get("final", {})
        result["effect_matches_recorded"] = (
            all(final.get(key) == original.get(key) for key in ("point", "event", "coverage", "normal_false_alarms_per_host_hour", "matched_delay_seconds"))
            if final.get("execution_status") == original.get("execution_status") == "SUCCEEDED" else None)
    except Exception as error:
        result.update({"status": "FAILED", "failure": failure(error)})
        if store.task(task_id)["phase"] not in {"FAILED", "COMPLETED"}:
            store.phase(task_id, "FAILED", result["failure"])
    finally:
        runner.cleanup_orphans()
    write_json(directory / "replay.json", result)
    return {**result, "directory": str(directory)}
