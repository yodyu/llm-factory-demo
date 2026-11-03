"""Task-level business adapters. Scheduling belongs to graph.py, not these functions."""

from contracts.base import strict_json_loads
from contracts.metrics import MetricsDataset, MetricsRequest, MetricsTask
from execution.metrics_runner import DEPENDENCY_PROFILE
from factory.metrics.evaluation import acceptance_result, select_development
from factory.metrics.execution_ops import trusted_labels, write_json
from factory.metrics.knowledge import canonical, identity, retrieve, verify_snapshot
from factory.metrics.planning import public_context, validate_detection_target
from factory.metrics.upload import load_upload
from factory.runtime.artifacts import digest

from . import GRAPH_VERSION, RECURSION_LIMIT


def task_actions(ctx, candidate_graph):
    def preflight(state):
        ctx.request = MetricsRequest.model_validate(ctx.task_input)
        ctx.manifest_raw = (ctx.dataset_root / "manifest.json").read_bytes()
        ctx.manifest = MetricsDataset.model_validate(strict_json_loads(ctx.manifest_raw))
        if ctx.request.expected_metric is not None and ctx.request.expected_metric != ctx.manifest.metric:
            raise ValueError("requested metric differs from dataset binding")
        ctx.upload = load_upload(ctx.dataset_root)
        ctx.legacy_upload = bool(ctx.upload and ctx.upload.get("pipeline") != "four-role-comparison/1")
        return {"data_mode": "legacy_upload" if ctx.legacy_upload else "uploaded_csv" if ctx.upload else "simulation"}

    def freeze_knowledge(state):
        if ctx.snapshot is None:
            ctx.snapshot, ctx.frozen_retrieval = ctx.knowledge.freeze(requirement=ctx.request.requirement,
                metric_kind=ctx.manifest.metric_kind, metric_name=ctx.manifest.metric, allowed_methods=ctx.request.allowed_methods,
                history_points=ctx.manifest.roles["development"].prefix_points,
                origin="llm_api" if ctx.gateway.client.profile.mode == "api" else "mock",
                enabled=ctx.retrieval_mode == "structured")
        verify_snapshot(ctx.snapshot)
        return {}

    def initialize(state):
        task = MetricsTask.model_validate({
            **ctx.request.model_dump(mode="json", exclude={"expected_metric", "schema_version"}),
            "task_id": ctx.requested_task_id, "dataset_id": ctx.manifest.dataset_id, "metric": ctx.manifest.metric,
            "knowledge_snapshot": ctx.snapshot["snapshot_id"], "model_mode": ctx.gateway.client.profile.mode,
            "model_profile_id": ctx.gateway.client.profile.profile_id})
        ctx.directory = ctx.state / "runs" / identity("task", task.task_id)
        ctx.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        ctx.store.create_task(task)
        ctx.task = task
        ctx.report = {"schema_version": "metrics-run/1", "task": task.model_dump(mode="json"),
            "knowledge_backend": ("local" if type(ctx.knowledge).__name__ == "LocalKnowledgeStore" else
                                  "neo4j" if type(ctx.knowledge).__name__ == "Neo4jKnowledgeStore" else "legacy_or_snapshot"),
            "origin": "fault_injection" if ctx.fault_injection else "llm_api" if task.model_mode == "api" else "mock",
            "knowledge_snapshot": ctx.snapshot, "retrieval_mode": ctx.retrieval_mode, "candidates": [],
            "prompt_version": ctx.gateway.prompt_version,
            "generation_protocol": 'capability-generation/2' if ctx.snapshot['schema_version'] == 'metrics-knowledge/2' else 'legacy-generation/1',
            "knowledge_off": ctx.retrieval_mode == 'knowledge_off',
            "dataset_public": {"metric": ctx.manifest.metric, "unit": ctx.manifest.unit, "metric_kind": ctx.manifest.metric_kind},
            "bindings": {"manifest_sha256": digest(ctx.manifest_raw), "knowledge_snapshot": ctx.snapshot["snapshot_id"], "image_id": ctx.image},
            "dependency_profile": DEPENDENCY_PROFILE, "final_test_executed": False, "status": "RUNNING",
            "runtime_scope": "scoring loop including causal preprocessing, IPC and output collection; prefix excluded",
            "limitations": ["synthetic data only", "only declared event recall/F1 and normal false-alarm gates supported"],
            "orchestration": {"engine": "langgraph", "graph_version": GRAPH_VERSION}}
        ctx.report["data_source"] = ctx.upload or {"type": "builtin_simulation", "display_name": ctx.manifest.dataset_id,
            "host_id": ctx.manifest.host_id, "metric": ctx.manifest.metric, "unit": ctx.manifest.unit,
            "sampling_seconds": ctx.manifest.sampling_seconds,
            "roles": {k: v.model_dump(mode="json") for k, v in ctx.manifest.roles.items()}}
        if ctx.upload:
            ctx.report["bindings"]["upload_sha256"] = digest((ctx.dataset_root / "upload.json").read_bytes())
            ctx.report["limitations"] = ["single host/metric", "user-assumed normal history; not verified", "no production generalization claim"]
        ctx.runner = ctx.runner_factory(ctx.store, ctx.store.artifact_store, ctx.state / "packages",
            ctx.state / "sandbox-work" / identity("task", task.task_id), image=ctx.image)
        return {"registered": True, "task_id": task.task_id, "candidate_cursor": 0, "candidate_result_refs": {},
                "request_ref": ctx.document(ctx.request.model_dump(mode="json"), "graph-request"),
                "manifest_ref": ctx.document(ctx.manifest.model_dump(mode="json"), "graph-manifest"),
                "task_ref": ctx.document(ctx.report["task"], "graph-task"),
                "snapshot_ref": ctx.document(ctx.snapshot, "graph-snapshot")}

    def bind(state):
        validate_detection_target(ctx.task)
        if ctx.task.requirement_draft:
            from contracts.metrics_requirement import RequirementDraft
            from factory.metrics.requirements import request_from_draft
            draft = RequirementDraft.model_validate(ctx.task.requirement_draft)
            expected = request_from_draft(draft, current_binding=draft.binding)
            for field in ("requirement", "anomaly_target", "explicit_constraints", "allowed_methods", "selection_policy", "acceptance_criteria"):
                if getattr(expected, field) != getattr(ctx.request, field):
                    raise ValueError("NEEDS_INPUT: frozen request differs from requirement draft: " + field)
            ctx.report["requirement_understanding"] = draft.model_dump(mode="json")
            write_json(ctx.directory / "requirement-draft.json", ctx.report["requirement_understanding"])
            if draft.parse_task_id:
                with ctx.store._transaction() as db:
                    artifacts = [dict(row) for row in db.execute(
                        "SELECT reference,role FROM task_artifacts WHERE task_id=?", (draft.parse_task_id,))]
                evidence = [{"role": item["role"], "document": ctx.store.document(item["reference"])} for item in artifacts]
                understanding = {"parse_task_id": draft.parse_task_id, "model_usage": draft.model_usage, "evidence": evidence}
                write_json(ctx.directory / "requirement-evidence.json", understanding)
                ctx.document(understanding, "requirement-evidence")
        ctx.load_role(ctx.dataset_root, ctx.manifest, "train")
        ctx.load_role(ctx.dataset_root, ctx.manifest, "calibration")
        if not ctx.legacy_upload:
            ctx.load_role(ctx.dataset_root, ctx.manifest, "development")
            labels, label_hash = trusted_labels(ctx.dataset_root, ctx.manifest, "development")
            ctx.report["bindings"]["labels_sha256"] = label_hash
            if labels is None:
                ctx.report["evaluation_policy"] = {
                    "mode": "engineering_only", "reason": "development labels unavailable",
                    "requested_selection_policy": ctx.task.selection_policy,
                    "effect_status": "NOT_EVALUATED", "label_dependent_acceptance": "NOT_EVALUATED"}
        write_json(ctx.directory / "task.json", ctx.report["task"])
        write_json(ctx.directory / "knowledge.json", ctx.snapshot)
        write_json(ctx.directory / "dataset-manifest.json", ctx.manifest.model_dump(mode="json"))
        ctx.store.phase(ctx.task.task_id, "DATA_READY", ctx.report["bindings"])
        ctx.report["input_ready"] = True

    def retrieve_knowledge(state):
        found = retrieve(ctx.snapshot, requirement=ctx.task.requirement, metric_kind=ctx.manifest.metric_kind,
            metric_name=ctx.manifest.metric, allowed_methods=ctx.task.allowed_methods, history_points=ctx.manifest.roles["development"].prefix_points,
            origin="llm_api" if ctx.task.model_mode == "api" else "mock", enabled=ctx.retrieval_mode == "structured")
        if ctx.frozen_retrieval is not None and ctx.frozen_retrieval != found:
            raise ValueError("frozen Neo4j retrieval differs from task view")
        if ctx.retrieval_mode == "knowledge_off":
            found["knowledge_off"] = True
        ctx.report["retrieval"] = found
        write_json(ctx.directory / "retrieval.json", found)
        if found.get("status") == "NO_RELEVANT_CAPABILITY":
            raise ValueError("NEEDS_INPUT: NO_RELEVANT_CAPABILITY: no relevant monitoring capability")
        ctx.store.phase(ctx.task.task_id, "KNOWLEDGE_READY", {"snapshot_id": ctx.snapshot["snapshot_id"], "knowledge_ids": found["knowledge_ids"]})
        train = ctx.load_role(ctx.dataset_root, ctx.manifest, "train")
        return {"retrieval_ref": ctx.document(found, "graph-retrieval"),
                "public_context_ref": ctx.document({**public_context(ctx.task, ctx.manifest, train, found),
                    "knowledge_off": ctx.retrieval_mode == "knowledge_off"}, "graph-public-context")}

    async def plan_candidates(state):
        planned = await ctx.plan(ctx.gateway, ctx.task, ctx.store.document(state["public_context_ref"]),
                                 ctx.store.document(state["retrieval_ref"]))
        ctx.report["planning"] = planned.model_dump(mode="json")
        write_json(ctx.directory / "plans.json", ctx.report["planning"])
        ctx.store.phase(ctx.task.task_id, "PLANNED", ctx.report["planning"])
        ctx.store.phase(ctx.task.task_id, "VALIDATING", {"candidate_ids": [c.candidate_id for c in planned.candidates]})
        order = [c.candidate_id for c in planned.candidates if not ctx.legacy_upload or c.config.method_id == ctx.upload["method"]]
        return {"plan_ref": ctx.document(ctx.report["planning"], "graph-plan"), "candidate_order": order}

    def next_candidate(state):
        order, cursor = state["candidate_order"], state["candidate_cursor"]
        return {"current_candidate_id": order[cursor] if cursor < len(order) else None}

    async def run_candidate(state):
        current = state["current_candidate_id"]
        planned = ctx.store.document(state["plan_ref"])
        plan = next(c for c in planned["candidates"] if c["candidate_id"] == current)
        ctx.active_candidate = None
        output = await candidate_graph.ainvoke({"candidate_id": current,
            "plan_ref": ctx.document(plan, "graph-candidate-plan"), "public_context_ref": state["public_context_ref"]},
            {"recursion_limit": RECURSION_LIMIT})
        return {"candidate_output": dict(output)}

    def record_candidate(state):
        output = state["candidate_output"]
        value = ctx.store.document(output["record_ref"])
        write_json(ctx.candidate_directory(value["candidate_id"]) / "candidate.json", value)
        ctx.report["candidates"].append(value)
        ctx.active_candidate = None
        refs = {**state["candidate_result_refs"], value["candidate_id"]: output["record_ref"]}
        update = {"candidate_result_refs": refs, "candidate_cursor": state["candidate_cursor"] + 1}
        if output.get("fatal"):
            update.update(error=output["error"], error_status="BUDGET_EXHAUSTED" if output["error"]["code"] == "BUDGET_EXHAUSTED" else "FAILED")
        return update

    def select(state):
        selection = ({"status": "USER_PRESELECTED_METHOD", "selected": next((c["candidate_id"] for c in ctx.report["candidates"]
            if c.get("report", {}).get("engineering_status") == "PASSED" and c.get("report", {}).get("execution_status") == "SUCCEEDED"), None),
            "ranking": [], "reason": "method selected before execution; no upload or benchmark effect used; no optimality claim"}
            if ctx.legacy_upload else select_development(ctx.report["candidates"], policy=ctx.task.selection_policy,
                                                       objective=ctx.task.evaluation_objective,
                                                       acceptance=ctx.task.acceptance_criteria, candidate_limit=ctx.task.budgets.candidates))
        ctx.report["selection"] = selection
        if selection["selected"] is None:
            if ctx.legacy_upload:
                messages = [c.get("failure", {}).get("message", c.get("failure", {}).get("code", "candidate unavailable"))
                            for c in ctx.report["candidates"]]
                prefix = "NEEDS_INPUT: " if any(c.get("calibration_status") == "FAILED" for c in ctx.report["candidates"]) else ""
                raise ValueError(prefix + "preselected method unavailable; " + "; ".join(messages))
            raise ValueError(("NEEDS_INPUT: " if selection["status"] == "NO_CANDIDATE_MEETS_ACCEPTANCE" else "") + selection["status"])

    def freeze_selection(state):
        selected = next(c for c in ctx.report["candidates"] if c["candidate_id"] == ctx.report["selection"]["selected"])
        freeze = {"task_sha256": ctx.store.task(ctx.task.task_id)["spec_hash"], "bindings": dict(ctx.report["bindings"]),
            "selected": selected["candidate_id"], "plan": selected["plan"], "source_path": selected["versions"][-1]["source_path"],
            "source_sha256": selected["versions"][-1]["source_sha256"], "threshold": selected["calibration"]["threshold"],
            "selection": ctx.report["selection"], "protocol": ctx.task.validation_protocol}
        freeze["selection_sha256"] = digest(canonical(freeze).encode())
        write_json(ctx.directory / "selection.json", freeze)
        ctx.store.phase(ctx.task.task_id, "SELECTED", freeze)
        return {"selection_ref": ctx.document(freeze, "graph-selection")}

    def final_evaluate(state):
        # The trusted evaluator receives no model gateway and the ledger forbids later model calls.
        ctx.report["final_evaluation_attempted"] = True
        ctx.report["final"] = ctx.final_evaluate(ctx.store, ctx.runner, ctx.task.task_id, ctx.dataset_root, ctx.directory)
        ctx.report["final_test_executed"] = ctx.report["final"].get("test_execution_started", False)
        return {"final_ref": ctx.document(ctx.report["final"], "graph-final-result")}

    def outcome(state):
        report = ctx.report
        report["business_acceptance"] = acceptance_result(report["final"], ctx.task.acceptance_criteria)
        if report["business_acceptance"]["status"] != "NOT_DEFINED":
            report["final"]["acceptance_status"] = report["business_acceptance"]["status"]
        if ctx.upload:
            report["benchmark"] = report["final"].pop("independent_benchmark", {"execution_status": "NOT_EVALUATED", "reason": "upload final stage failed"})
        report["curves"] = report["final"].pop("curves", {})
        if not ctx.upload and report["curves"].get("detection"):
            from factory.metrics.upload import read_curve
            rows = read_curve(ctx.directory, report["curves"]["detection"])["rows"]
            report["data_source"].update(points=len(rows), start_at=rows[0]["timestamp"], end_at_inclusive=rows[-1]["timestamp"],
                                       missing_points=sum(r["value"] is None for r in rows))
        ctx.store.phase(ctx.task.task_id, "FINAL_EVALUATED", report["final"])
        selected = next(c for c in report["candidates"] if c["candidate_id"] == report["selection"]["selected"])
        report["status"] = "COMPLETED" if report["final"]["execution_status"] == "SUCCEEDED" else "FAILED"
        report["stage_status"] = {"engineering": selected["report"]["engineering_status"], "detection": report["final"]["execution_status"],
                                  "benchmark": report.get("benchmark", {}).get("execution_status", "NOT_APPLICABLE")}
        report["completion_status"] = "PARTIAL_SUCCESS" if report["stage_status"]["detection"] == "SUCCEEDED" and report["stage_status"]["benchmark"] == "FAILED" else report["status"]
        ctx.store.phase(ctx.task.task_id, report["status"],
            {"final": report["final"], "acceptance_status": report["final"].get("acceptance_status")} if report["status"] == "COMPLETED" else report["final"])

    return {"preflight": preflight, "freeze_knowledge": freeze_knowledge, "initialize_task": initialize,
        "bind_inputs": bind, "retrieve_knowledge": retrieve_knowledge, "plan_candidates": plan_candidates,
        "next_candidate": next_candidate, "run_candidate": run_candidate, "record_candidate": record_candidate,
        "select_candidate": select, "freeze_selection": freeze_selection, "final_evaluate": final_evaluate,
        "resolve_outcome": outcome}
