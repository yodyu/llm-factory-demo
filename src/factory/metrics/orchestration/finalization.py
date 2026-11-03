"""Shared, idempotent normal and exceptional finalization without business replay."""
from factory.metrics.capability_registry import registry

from copy import deepcopy
from importlib.metadata import version
import json
import time

from contracts.base import strict_json_loads
from factory.metrics.execution_ops import failure
from factory.runtime.artifacts import digest

from . import GRAPH_VERSION


TERMINAL = {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "NEEDS_INPUT"}


def write_same(path, value):
    """Never overwrite evidence. Retrying incomplete finalization may only reuse identical data."""
    if path.exists():
        if path.is_symlink() or strict_json_loads(path.read_bytes()) != value:
            raise ValueError("immutable finalization evidence conflict")
        return
    with path.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def record_failure(ctx, state):
    info = state["error"]
    current = ctx.store.task(ctx.task.task_id)["phase"]
    if current in TERMINAL and ctx.report.get("status") in TERMINAL:
        # Graph boundaries introduce cancellation points after the business
        # outcome is committed. Preserve that outcome while recording the
        # separate failure to finish orchestration/delivery.
        ctx.report.setdefault("finalization_failure", info)
        return
    ctx.report.update(status=state.get("error_status", "FAILED"), failure=info)
    if current not in TERMINAL:
        ctx.store.phase(ctx.task.task_id, ctx.report["status"], info)
    if ctx.active_candidate and not any(c["candidate_id"] == ctx.active_candidate["candidate_id"] for c in ctx.report["candidates"]):
        candidate = deepcopy(ctx.active_candidate)
        candidate.setdefault("failure", info)
        candidate.setdefault("report", {"execution_status": "FAILED", "engineering_status": "FAILED", "effect_status": "NOT_MEASURED"})
        ctx.report["candidates"].append(candidate)
        ctx.active_candidate = None
        try:
            write_same(ctx.candidate_directory(candidate["candidate_id"]) / "candidate.json", candidate)
        except Exception as artifact_error:
            ctx.report["candidate_artifact_failure"] = failure(artifact_error)


def cleanup(ctx, state=None):
    if ctx.cleaned:
        return {}
    result = {"status": "SUCCEEDED"}
    try:
        if ctx.runner is not None:
            ctx.runner.cleanup_orphans()
    except Exception as error:
        result = {"status": "FAILED", "failure": failure(error)}
        ctx.report["cleanup_failure"] = result["failure"]
    ctx.cleaned = True
    return {"cleanup_result": result}


def write_report(ctx, state=None):
    if ctx.report_frozen:
        return {}
    if ctx.sealed_report is None:
        report = ctx.report
        if (report.get("status") != "COMPLETED" and report.get("input_ready")
            and not report.get("final_test_executed")
            and report.get("retrieval", {}).get("status") != "NO_RELEVANT_CAPABILITY"):
            proposed = report.get("planning", {}).get("candidates")
            origin = "model_plan" if proposed else "confirmed_requirement_outline"
            if not proposed:
                proposed = [{"candidate_id": "proposal-" + method,
                    "config": {"method_id": method, "direction": ctx.task.anomaly_target, **{
                        k: v for k, v in ctx.task.explicit_constraints.items() if k in (
                            set(registry().get(method).config_schema["properties"]))}},
                    "limitations": ["根据已确认需求整理；尚未完成模型规划与代码验证，未填写参数仍待确定。"]}
                    for method in ctx.task.allowed_methods]
            report["proposal"] = {"status": "PLAN_ONLY", "origin": origin, "candidates": proposed,
                "notice": ("检测方案已生成，但尚无通过验证的可运行结果；以下为方案草稿，不代表算法已运行或效果达标。"
                           if origin == "model_plan" else "模型规划尚未完成，已根据确认需求整理方案草稿；没有运行代码或测量效果。")}
            report["completion_status"] = "PLAN_ONLY"
        report["workflow_runtime_seconds"] = time.monotonic() - ctx.started
        report["resource_measurement"] = {"peak_memory_bytes": None, "cpu_seconds": None, "reason": "not_measured; sandbox limits are not measurements"}
        report.setdefault("stage_status", {"engineering": "PASSED" if any(c.get("report", {}).get("engineering_status") == "PASSED" for c in report["candidates"]) else "FAILED",
                                          "detection": "NOT_EVALUATED", "benchmark": "NOT_EVALUATED"})
        report["campaign_budget"] = ctx.store.campaign.summary() if ctx.store.campaign else None
        with ctx.store._transaction() as db:
            report["model_operations"] = [dict(row) for row in db.execute(
                "SELECT operation_id,status,result_ref,metadata FROM operations WHERE task_id=? AND resource='model' ORDER BY reserved_at",
                (ctx.task.task_id,))]
        from factory.metrics.usage import model_usage
        report["model_usage"] = model_usage(report)
        from pathlib import Path
        modules = sorted(Path(__file__).parent.glob("*.py"))
        modules += [Path(__file__).parent.parent / name for name in ("workflow.py", "execution_ops.py")]
        source_hash = digest(b"".join(p.name.encode() + b"\0" + p.read_bytes() for p in modules))
        evidence = {"schema_version": "metrics-orchestration/1", "engine": "langgraph", "graph_version": GRAPH_VERSION,
            "langgraph_version": version("langgraph"), "source_sha256": source_hash, "task_id": ctx.task.task_id,
            "workflow_status": report["status"], "events": deepcopy([e for e in ctx.events if e["node"] not in {"write_report", "publish", "export"}]),
            "scope": "execution through cleanup; publication and export have separate receipts"}
        ctx.store.guard.require_public(evidence)
        raw = (json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        report["orchestration"] = {"engine": "langgraph", "graph_version": GRAPH_VERSION,
            "evidence_path": "orchestration.json", "evidence_sha256": digest(raw)}
        ctx.sealed_evidence, ctx.sealed_report = evidence, deepcopy(report)
    write_same(ctx.directory / "orchestration.json", ctx.sealed_evidence)
    ctx.document(ctx.sealed_evidence, "orchestration-evidence")
    write_same(ctx.directory / "report.json", ctx.sealed_report)
    from factory.metrics.reports import markdown
    text = markdown(ctx.sealed_report)
    path = ctx.directory / "report.md"
    if path.exists():
        if path.is_symlink() or path.read_text() != text:
            raise ValueError("immutable report markdown conflict")
    else:
        with path.open("x") as stream:
            stream.write(text)
    ref = ctx.document(ctx.sealed_report, "run-report")
    ctx.report = deepcopy(ctx.sealed_report)
    ctx.report_frozen = True
    return {"report_ref": ref}


def publish(ctx, state=None):
    if ctx.publication is None:
        try:
            from factory.metrics.publication import publish_pending
            ctx.publication = publish_pending(ctx.store, ctx.knowledge, ctx.sealed_report)
        except Exception as error:
            ctx.publication = {"status": "PENDING_RETRY", "failure": failure(error)}
    write_same(ctx.directory / "publication.json", ctx.publication)
    return {"publication_ref": ctx.document(ctx.publication, "graph-publication")}


def export(ctx, state=None):
    if ctx.export_result is None:
        try:
            from factory.metrics.reports import export_run
            result = export_run(ctx.store, ctx.directory, ctx.directory / "delivery.zip", dataset_root=ctx.dataset_root)
            ctx.export_result = {"status": "SUCCEEDED", **result}
        except Exception as error:
            ctx.export_result = {"status": "FAILED", "failure": failure(error)}
    write_same(ctx.directory / "export.json", ctx.export_result)
    return {"export_result": ctx.export_result}


def emergency_finalize(ctx, error, *, cancelled=False):
    """Synchronous, bounded best effort. Never invoke a model or restart graph execution."""
    if not ctx.registered:
        return
    errors = []
    if not ctx.report_frozen and ctx.sealed_report is None:
        info = {"code": "INTERRUPTED", "message": "task interrupted; uncertain requests remain charged and are not retried"} if cancelled else failure(error)
        if cancelled:
            try:
                ctx.store.recover_uncertain(ctx.task.task_id)
            except Exception as recovery_error:
                errors.append(failure(recovery_error))
        try:
            record_failure(ctx, {"error": info, "error_status": "FAILED"})
        except Exception as record_error:
            errors.append(failure(record_error))
    for action in (cleanup, write_report, publish):
        try:
            action(ctx)
        except Exception as finalization_error:
            errors.append(failure(finalization_error))
            if action == write_report:
                break
    if errors:
        write_same(ctx.directory / "finalization-errors.json", {"primary": failure(error), "failures": errors})
