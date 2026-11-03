# Backward compatibility: frozen pre-plugin two-method experiment protocol.
"""Budget-limited first-response code ablation with identical manually fixed plans.

This is a code-generation experiment, not a full-agent or business-effect claim.
No retries, format correction, repair, candidate selection or test data are used.
"""

from contracts.base import strict_json_loads
from contracts.metrics import CandidatePlan, FixedConfig, MADConfig, MetricsBudgets, MetricsDataset, MetricsTask
from contracts.metrics_knowledge import GeneratedCode
from execution.metrics_runner import MetricsRunner, DEPENDENCY_PROFILE
from factory.metrics.data import load_role
from factory.metrics.generation import INTERFACE
from factory.metrics.knowledge import identity, retrieve
from factory.metrics.planning import public_context
from factory.metrics.reports import markdown
from factory.metrics.service import open_runtime
from factory.metrics.legacy_validation import validate_candidate
from factory.metrics.workflow import execute, failure, write_json
from factory.runtime.artifacts import digest


async def focused(args):
    from factory.metrics.knowledge_store import open_knowledge
    with open_knowledge(args.knowledge) as knowledge:
        snapshot = knowledge.snapshot()
    dataset_raw = (args.dataset / "manifest.json").read_bytes()
    dataset = MetricsDataset.model_validate(strict_json_loads(dataset_raw))
    request = strict_json_loads(args.task.read_bytes())
    store, gateway = open_runtime(args.state, mode=args.mode, campaign=args.campaign, env_file=args.env_file)
    gateway.client.max_attempts = 1
    gateway.format_corrections = 0
    if store.campaign and store.campaign.summary()["remaining"] < 4:
        raise ValueError("four reserved campaign slots required for the complete focused comparison")
    args.output.mkdir(parents=True, exist_ok=False)
    plans = [CandidatePlan(candidate_id="fixed", config=FixedConfig(threshold=request["explicit_constraints"]["threshold"]),
                           parameter_sources={"threshold": "user_explicit"}, knowledge_ids=[], limitations=[]),
             CandidatePlan(candidate_id="mad", config=MADConfig(), parameter_sources={"window": "protocol_default"}, knowledge_ids=[], limitations=[])]
    train = load_role(args.dataset, dataset, "train")
    freeze = {"protocol": "metrics-fixed-plan-first-response/1", "model_profile": gateway.client.profile.model_dump(mode="json"),
              "prompt_version": gateway.prompt_version, "method_validation_protocol": "metrics-method-check/2",
              "plans": [p.model_dump(mode="json") for p in plans], "conditions": ["none", "structured"],
              "snapshot_id": snapshot["snapshot_id"], "manifest_sha256": digest(dataset_raw),
              "scope": "one first response per method and condition; no model planning, retries, corrections, repair or effect evaluation"}
    write_json(args.output / "frozen.json", freeze)
    arms = []
    try:
        for condition in freeze["conditions"]:
            task_id = args.prefix + "-" + condition
            task = MetricsTask(task_id=task_id, requirement=request["requirement"], dataset_id=dataset.dataset_id,
                    metric=dataset.metric, anomaly_target="upper", explicit_constraints=request["explicit_constraints"], ranking_preferences=[],
                    allowed_methods=["fixed_threshold", "rolling_mad"], knowledge_snapshot=snapshot["snapshot_id"],
                    model_mode=gateway.client.profile.mode, model_profile_id=gateway.client.profile.profile_id,
                    budgets=MetricsBudgets(model_calls=2, repair_rounds=0))
            store.create_task(task)
            store.set_task_status(task_id, "RUNNING")
            directory = args.state / "runs" / identity("task", task_id)
            directory.mkdir(parents=True, exist_ok=False)
            runner = MetricsRunner(store, store.artifact_store, args.state / "packages", directory / "sandbox", image=args.image)
            retrieval = retrieve(snapshot, requirement=task.requirement, metric_kind=dataset.metric_kind,
                        allowed_methods=task.allowed_methods, history_points=dataset.roles["development"].prefix_points,
                        enabled=condition == "structured", origin="llm_api" if args.mode == "api" else "mock")
            context = public_context(task, dataset, train, retrieval)
            report = {"schema_version": "metrics-run/1", "task": task.model_dump(mode="json"), "origin": "llm_api" if args.mode == "api" else "mock",
                      "status": "METHOD_AUDIT_ONLY", "scope": freeze["scope"], "knowledge_snapshot": snapshot, "retrieval": retrieval,
                      "retrieval_mode": condition, "dataset_public": {"metric": dataset.metric, "unit": dataset.unit, "metric_kind": dataset.metric_kind},
                      "bindings": {"manifest_sha256": digest(dataset_raw), "knowledge_snapshot": snapshot["snapshot_id"], "image_id": args.image,
                                   "labels_sha256": digest((args.dataset / "trusted" / "labels.json").read_bytes())},
                      "dependency_profile": DEPENDENCY_PROFILE, "candidates": [], "model_operations": [],
                      "final_test_executed": False, "effect_status": "NOT_MEASURED"}
            write_json(directory / "task.json", report["task"])
            write_json(directory / "knowledge.json", snapshot)
            write_json(directory / "dataset-manifest.json", dataset.model_dump(mode="json"))
            write_json(directory / "retrieval.json", retrieval)
            for plan in plans:
                candidate = {"candidate_id": plan.candidate_id, "role": "development", "plan": plan.model_dump(mode="json"), "versions": []}
                report["candidates"].append(candidate)
                try:
                    code = await gateway.ask(task_id, "code-" + plan.candidate_id + "-v0", GeneratedCode,
                           {"task": context, "frozen_plan": candidate["plan"], "version": 0}, INTERFACE)
                    if not set(code.knowledge_ids) <= set(retrieval["knowledge_ids"]):
                        raise ValueError("citation outside frozen context")
                    folder = directory / identity("candidate", plan.candidate_id)
                    folder.mkdir()
                    path = folder / "v0.py"
                    path.write_text(code.source)
                    ref = store.artifact_store.put(code.source.encode())
                    store.attach_artifact(task_id, ref, len(code.source.encode()), "candidate-source")
                    version = {"version": 0, "origin": report["origin"], "source_path": str(path.relative_to(directory)),
                               "source_sha256": ref, "source_ref": ref, "knowledge_ids": code.knowledge_ids}
                    candidate["versions"].append(version)
                    checks = execute(store, task_id, "check-" + plan.candidate_id, {"source": ref, "config": candidate["plan"]},
                              lambda: validate_candidate(runner, task_id, code.source, plan.config, candidate_id=plan.candidate_id, version=0, origin=report["origin"]))
                    version["validation"] = checks
                    write_json(folder / "v0-checks.json", checks)
                    candidate["first_response_passed"] = checks["passed"]
                except Exception as error:
                    candidate.update({"first_response_passed": False, "failure": failure(error)})
            runner.cleanup_orphans()
            with store._transaction() as db:
                report["model_operations"] = [dict(r) for r in db.execute("SELECT operation_id,status,result_ref,metadata FROM operations WHERE task_id=? AND resource='model' ORDER BY reserved_at", (task_id,))]
            report["campaign_budget"] = store.campaign.summary() if store.campaign else None
            write_json(directory / "report.json", report)
            (directory / "report.md").write_text(markdown(report))
            store.register_document(task_id, report, "run-report")
            store.set_task_status(task_id, "SUCCEEDED")  # audit finished; individual engineering outcomes are separate
            arms.append({"condition": condition, "task_id": task_id, "directory": str(directory),
                         "attempts": len(report["candidates"]), "first_response_passed": sum(c["first_response_passed"] for c in report["candidates"]),
                         "candidates": [{"method": c["plan"]["config"]["method_id"], "passed": c["first_response_passed"], "failure": c.get("failure")} for c in report["candidates"]]})
    finally:
        await gateway.client.aclose()
    result = {"protocol": freeze["protocol"], "arms": arms, "model_requests_planned": 4,
              "campaign_budget": store.campaign.summary() if store.campaign else None,
              "interpretation": "one constructed task, two methods; exploratory first-response code checks only; no statistical, repair-benefit or business-effect claim"}
    write_json(args.output / "summary.json", result)
    return result
