"""Numeric CLI service wiring. API requests always share an explicit campaign DB."""
from factory.metrics.capability_registry import default_methods

import json
from pathlib import Path
from uuid import uuid4

from contracts.metrics import MetricsBudgets, MetricsTask
from factory.metrics.budget import CallBudget
from factory.metrics.knowledge import KnowledgeStore, ingest
from factory.metrics.model import make_gateway
from factory.metrics.runtime import MetricsStore
from factory.runtime.artifacts import digest


def open_runtime(state, *, mode, campaign=None, env_file=None):
    state = Path(state)
    if mode == "api" and campaign is None:
        raise ValueError("API mode requires --campaign pointing to the shared 60-call budget")
    store = MetricsStore(state / "runtime.sqlite", campaign=CallBudget(campaign) if mode == "api" else None)
    gateway = make_gateway(store, env_file, mode=mode)
    return store, gateway


def register_ingest(store, gateway, task_id):
    store.create_task(MetricsTask(task_id=task_id, requirement="重新导入材料并抽取有来源的数值监控知识",
                      dataset_id="materials", metric="numeric", anomaly_target="knowledge_extraction",
                      explicit_constraints={"purpose": "knowledge_ingest"}, ranking_preferences=[],
                      allowed_methods=default_methods(), knowledge_snapshot=digest(b"{}"),
                      budgets=MetricsBudgets(), model_mode=gateway.client.profile.mode,
                      model_profile_id=gateway.client.profile.profile_id))


async def ingest_command(args):
    knowledge = KnowledgeStore(args.knowledge)
    try:
        knowledge.snapshot()
    except BaseException:
        knowledge.close()
        raise
    # Fail before any model call when graph is unavailable.
    store, gateway = open_runtime(args.state, mode=args.mode, campaign=args.campaign, env_file=args.env_file)
    task_id = args.task_id or "ingest-" + uuid4().hex[:16]
    try:
        if args.output.exists():
            raise FileExistsError("snapshot output already exists")
        register_ingest(store, gateway, task_id)
        store.set_task_status(task_id, "RUNNING")
        from factory.metrics.capability_knowledge import register_plugins
        register_plugins(knowledge)
        if getattr(args, 'repo', None):
            from factory.metrics.repository_ingest import repository_sources
            args.root = args.repo
            paths = repository_sources(args.repo)
        else:
            paths = args.sources or [path.name for path in sorted(args.root.iterdir()) if path.suffix in {".md", ".txt", ".py"}]
        result = await ingest(args.root, paths, knowledge, gateway, task_id,
                              origin="llm_api" if args.mode == "api" else "mock")
        with args.output.open("x") as stream:
            stream.write(json.dumps(result["snapshot"], ensure_ascii=False, indent=2) + "\n")
        checks = {"task_id": task_id, "origin": result["origin"], "sources": result["sources"],
                  "status": "SUCCEEDED" if all(r["status"] == "source_checked" for r in result["sources"]) else "FAILED",
                  "snapshot_id": result["snapshot"]["snapshot_id"],
                  "budget": store.campaign.summary() if store.campaign else None}
        store.register_document(task_id, checks, "ingest-report")
        store.set_task_status(task_id, "SUCCEEDED" if all(r["status"] == "source_checked" for r in result["sources"]) else "FAILED")
        with args.output.with_suffix(".ingest.json").open("x") as stream:
            stream.write(json.dumps(checks, ensure_ascii=False, indent=2) + "\n")
        return checks
    except BaseException:
        try:
            if store.task(task_id)["status"] not in {"SUCCEEDED", "FAILED"}:
                store.set_task_status(task_id, "FAILED")
        except KeyError:
            pass
        raise
    finally:
        await gateway.client.aclose()
        knowledge.close()


async def run_command(args):
    from contracts.base import strict_json_loads
    from factory.metrics.workflow import run

    knowledge = KnowledgeStore(args.knowledge)
    gateway = None
    try:
        # Current CLI/Web submissions register source-linked expert cards before
        # freezing. Only the explicit workflow compatibility API accepts v1 snapshots.
        from factory.metrics.capability_knowledge import register_plugins
        register_plugins(knowledge)
        store, gateway = open_runtime(args.state, mode=args.mode, campaign=args.campaign, env_file=args.env_file)
        result = await run(store, gateway, state=args.state.resolve(),
                         task_input=strict_json_loads(args.task.read_bytes()), dataset_root=args.dataset,
                         knowledge=knowledge,
                         image=args.image, retrieval_mode=args.retrieval, task_id=args.task_id,
                         fault_injection=args.fault_injection, export_delivery=True)
        return result
    finally:
        if gateway is not None:
            await gateway.client.aclose()
        knowledge.close()
