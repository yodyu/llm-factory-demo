"""Compatibility entrypoint for the LangGraph task and candidate graphs."""

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from execution.metrics_runner import MetricsRunner
from factory.metrics.data import load_role
from factory.metrics.execution_ops import (
    FAULT as FAULT,
    decode_scores as decode_scores,
    execute as execute,
    failure as failure,
    role_scores as role_scores,
    trusted_labels as trusted_labels,
    write_json as write_json,
    final_evaluate as _final_evaluate,
)
from factory.metrics.generation import generate
from factory.metrics.planning import plan
from factory.runtime.locks import _task_lock


# Retained for callers and historical replay; the evaluator has no model dependency.
def final_evaluate(store, runner, task_id, dataset_root, directory):
    return _final_evaluate(store, runner, task_id, dataset_root, directory, role_loader=load_role)


async def run(store, gateway, *, state, task_input, dataset_root, snapshot=None, knowledge, image,
              retrieval_mode="structured", task_id=None, fault_injection=False, frozen_retrieval=None,
              export_delivery=False):
    from factory.metrics.orchestration import GRAPH_VERSION, RECURSION_LIMIT
    from factory.metrics.orchestration.finalization import emergency_finalize
    from factory.metrics.orchestration.graph import build_task_graph
    from factory.metrics.orchestration.state import RunContext

    task_id = task_id or "metrics-" + uuid4().hex[:16]
    ctx = RunContext(store=store, gateway=gateway, knowledge=knowledge, state=Path(state),
        dataset_root=Path(dataset_root), task_input=task_input, image=image,
        snapshot=snapshot, frozen_retrieval=frozen_retrieval, retrieval_mode=retrieval_mode,
        requested_task_id=task_id, fault_injection=fault_injection, export_delivery=export_delivery,
        generate=generate, plan=plan, final_evaluate=final_evaluate, load_role=load_role,
        runner_factory=MetricsRunner)
    with _task_lock(ctx.state / "locks", task_id):
        try:
            graph = build_task_graph(ctx)
            output = await graph.ainvoke({"graph_version": GRAPH_VERSION, "registered": False, "error": None},
                                        {"recursion_limit": RECURSION_LIMIT})
        except BaseException as error:
            cancelled = ctx.cancelled or isinstance(error, asyncio.CancelledError)
            try:
                emergency_finalize(ctx, error, cancelled=cancelled)
            except Exception as cleanup_error:
                logging.getLogger(__name__).error("Exceptional finalization failed (%s)", type(cleanup_error).__name__)
            if cancelled and not isinstance(error, asyncio.CancelledError):
                raise asyncio.CancelledError() from error
            raise
    if output.get("export_result", {}).get("status") == "FAILED":
        raise RuntimeError("delivery export failed; frozen report and export.json retained")
    report = ctx.report
    return {"task_id": task_id, "status": report.get("completion_status", report["status"]),
            "workflow_status": report["status"], "stage_status": report["stage_status"],
            "directory": str(ctx.directory), "publication": ctx.publication,
            "campaign_budget": report["campaign_budget"]}
