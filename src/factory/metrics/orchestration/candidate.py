"""A candidate is a real StateGraph with explicit bounded repair edges."""
from factory.metrics.capability_registry import needs_calibration

from copy import deepcopy

from langgraph.graph import END, START, StateGraph

from contracts.metrics import CandidatePlan
from factory.metrics.evaluation import acceptance_result, calibrate
from factory.metrics.execution_ops import FAULT, decode_scores, execute, role_scores, write_json
from factory.metrics.knowledge import canonical
from factory.metrics.validation import validate_candidate
from factory.runtime.artifacts import digest

from .events import node
from .state import CandidateInput, CandidateOutput, CandidateState


def build_candidate_graph(ctx):
    def record(state):
        value = deepcopy(ctx.store.document(state["record_ref"]))
        ctx.active_candidate = value
        return value

    def save(value):
        ctx.active_candidate = deepcopy(value)
        return ctx.document(value, "graph-candidate-progress")

    def prepare(state):
        plan = ctx.store.document(state["plan_ref"])
        value = {"candidate_id": state["candidate_id"],
                 "role": "preselected_upload" if ctx.legacy_upload else "development",
                 "plan": plan, "versions": []}
        ctx.active_candidate = deepcopy(value)
        ctx.candidate_directory(state["candidate_id"]).mkdir()
        return {"record_ref": save(value), "version": 0, "error": None, "fatal": False}

    async def generate(state):
        record(state)
        plan = CandidatePlan.model_validate(ctx.store.document(state["plan_ref"]))
        previous = ctx.store.artifact_store.read(state["source_ref"]).decode() if state.get("source_ref") else None
        feedback = ctx.store.document(state["validation_ref"]) if state.get("validation_ref") else None
        generated = await ctx.generate(ctx.gateway, ctx.task, plan,
            ctx.store.document(state["public_context_ref"]), version=state["version"],
            previous=previous, feedback=feedback)
        return {"generated_ref": ctx.document(generated.model_dump(mode="json"), "graph-generated-code")}

    def persist(state):
        value = record(state)
        plan = CandidatePlan.model_validate(value["plan"])
        generated = ctx.store.document(state["generated_ref"])
        source = generated["source"]
        version = state["version"]
        origin = "llm_api" if ctx.task.model_mode == "api" else "mock"
        folder = ctx.candidate_directory(state["candidate_id"])
        if ctx.fault_injection and version == 0 and not needs_calibration(plan.config):
            with (folder / "model-original-v0.py").open("x") as stream:
                stream.write(source)
            source += FAULT
            origin = "fault_injection"
        ctx.store.guard.require_public(source)
        path = folder / f"v{version}.py"
        with path.open("x") as stream:
            stream.write(source)
        ref = ctx.store.artifact_store.put(source.encode())
        ctx.store.attach_artifact(ctx.task.task_id, ref, len(source.encode()), "candidate-source")
        entry = {"version": version, "origin": origin, "source_path": str(path.relative_to(ctx.directory)),
                 "source_sha256": ref, "source_ref": ref, "parent_source_sha256": state.get("source_ref"),
                 "knowledge_ids": generated["knowledge_ids"], "explanation": generated["explanation"],
                 **{k: generated.get(k) for k in ('capability_id', 'capability_version', 'specification_sha256', 'plugin_hashes')}}
        value["versions"].append(entry)
        ctx.active_candidate = deepcopy(value)
        impl_ref = ctx.document(entry, "implementation")
        if state.get("repair_op"):
            ctx.store.mark_operation(state["repair_op"], "SUCCEEDED", impl_ref)
        return {"source_ref": ref, "record_ref": save(value)}

    def validate(state):
        value = record(state)
        plan = CandidatePlan.model_validate(value["plan"])
        source = ctx.store.artifact_store.read(state["source_ref"]).decode()
        entry = value["versions"][-1]
        result = execute(ctx.store, ctx.task.task_id, f"check-{state['candidate_id']}-v{state['version']}",
            {**entry, "plan": value["plan"], "image": ctx.image},
            lambda: validate_candidate(ctx.runner, ctx.task.task_id, source, plan.config,
                candidate_id=state["candidate_id"], version=state["version"], origin=entry["origin"], expected_plugin_hashes=entry.get("plugin_hashes")))
        entry["validation"] = result
        ctx.active_candidate = deepcopy(value)
        write_json(ctx.candidate_directory(state["candidate_id"]) / f"v{state['version']}-checks.json", result)
        return {"validation_ref": ctx.document(result, "graph-validation"), "record_ref": save(value)}

    def repair(state):
        result = ctx.store.document(state["validation_ref"])
        version = state["version"] + 1
        op = f"{ctx.task.task_id}:repair:{state['candidate_id']}:{version}"
        ctx.store.reserve(ctx.task.task_id, "repair", op, digest(canonical(result).encode()))
        ctx.store.mark_operation(op, "SENT")
        return {"version": version, "repair_op": op}

    def calibrate_candidate(state):
        value = record(state)
        plan = CandidatePlan.model_validate(value["plan"])
        source = ctx.store.artifact_store.read(state["source_ref"]).decode()
        binding = {"source": state["source_ref"], "config": plan.config.model_dump(mode="json"),
                   "dataset": ctx.report["bindings"]}
        result = {"threshold": 0.0, "rule": "fixed_parameter_unchanged", "labels_used": False}
        if needs_calibration(plan.config):
            prefix = ctx.manifest.roles["calibration"].prefix_points
            train = ctx.load_role(ctx.dataset_root, ctx.manifest, "train")
            points = ctx.load_role(ctx.dataset_root, ctx.manifest, "calibration")
            scores = execute(ctx.store, ctx.task.task_id, "calibrate-" + state["candidate_id"], binding,
                lambda: role_scores(ctx.runner, ctx.task.task_id, source, plan.config, train, points, prefix))
            result = calibrate(decode_scores(scores), quantile=plan.config.quantile, prefix_points=prefix)
        value.update(calibration={**result, "binding": binding}, calibration_status="SUCCEEDED")
        return {"record_ref": save(value)}

    def development(state):
        from factory.metrics.execution_ops import trusted_labels
        from factory.metrics.upload import detection_result
        value = record(state)
        plan = CandidatePlan.model_validate(value["plan"])
        source = ctx.store.artifact_store.read(state["source_ref"]).decode()
        prefix = ctx.manifest.roles["development"].prefix_points
        train = ctx.load_role(ctx.dataset_root, ctx.manifest, "train")
        points = ctx.load_role(ctx.dataset_root, ctx.manifest, "development")
        labels, _ = trusted_labels(ctx.dataset_root, ctx.manifest, "development")
        scores = execute(ctx.store, ctx.task.task_id, "development-" + state["candidate_id"],
            value["calibration"]["binding"],
            lambda: role_scores(ctx.runner, ctx.task.task_id, source, plan.config, train, points, prefix))
        value["report"] = detection_result(points, decode_scores(scores), manifest=ctx.manifest, prefix=prefix,
            threshold=value["calibration"]["threshold"], elapsed=scores["elapsed_seconds"],
            persistence=plan.persistence_points, labels=labels[prefix:] if labels is not None else None)
        return {"record_ref": save(value)}

    def finish(state):
        value = record(state)
        if ctx.legacy_upload:
            value["report"] = {"execution_status": "SUCCEEDED", "engineering_status": "PASSED", "effect_status": "NOT_EVALUATED"}
        value["business_acceptance"] = acceptance_result(value["report"], ctx.task.acceptance_criteria)
        return {"record_ref": save(value)}

    def fail(state):
        value = deepcopy(ctx.active_candidate) if ctx.active_candidate else record(state)
        info = state.get("error")
        if not info:
            validation = ctx.store.document(state["validation_ref"])
            info = {"code": "CANDIDATE_ERROR", "feedback": {
                "code": "METHOD_VALIDATION_FAILED", "checks": validation["checks"]}}
        value["failure"] = info
        passed = bool(value["versions"] and value["versions"][-1].get("validation", {}).get("passed"))
        value["report"] = {"execution_status": "FAILED", "engineering_status": "PASSED" if ctx.upload and passed else "FAILED",
                           "effect_status": "NOT_MEASURED"}
        if ctx.upload and passed and "calibration" not in value:
            value["calibration_status"] = "FAILED"
        value["business_acceptance"] = acceptance_result(value["report"], ctx.task.acceptance_criteria)
        return {"record_ref": save(value)}

    def after_validation(state):
        if state.get("error"):
            return "fail"
        result = ctx.store.document(state["validation_ref"])
        if result["passed"]:
            return "calibrate"
        if result["repairable"] and state["version"] < ctx.task.budgets.repair_rounds:
            return "repair"
        return "fail"

    graph = StateGraph(CandidateState, input_schema=CandidateInput, output_schema=CandidateOutput)
    actions = {"prepare_candidate": prepare, "generate_version": generate, "persist_version": persist,
               "validate_version": validate, "reserve_repair": repair, "calibrate_candidate": calibrate_candidate,
               "evaluate_development": development, "finish_candidate": finish, "fail_candidate": fail}
    for name, action in actions.items():
        graph.add_node(name, node(ctx, name, action, candidate=True, propagate=name == "fail_candidate"))
    graph.add_edge(START, "prepare_candidate")
    for source, target in (("prepare_candidate", "generate_version"), ("generate_version", "persist_version"),
                           ("persist_version", "validate_version"), ("reserve_repair", "generate_version"),
                           ("evaluate_development", "finish_candidate")):
        graph.add_conditional_edges(source, lambda s: "fail" if s.get("error") else "next",
                                    {"fail": "fail_candidate", "next": target})
    graph.add_conditional_edges("validate_version", after_validation,
        {"fail": "fail_candidate", "calibrate": "calibrate_candidate", "repair": "reserve_repair"})
    graph.add_conditional_edges("calibrate_candidate",
        lambda s: "fail" if s.get("error") else "finish" if ctx.legacy_upload else "development",
        {"fail": "fail_candidate", "finish": "finish_candidate", "development": "evaluate_development"})
    graph.add_conditional_edges("finish_candidate", lambda s: "fail" if s.get("error") else "done",
                                {"fail": "fail_candidate", "done": END})
    graph.add_edge("fail_candidate", END)
    return graph.compile()
