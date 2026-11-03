"""Numeric monitoring factory: ingest, generate, validate, evaluate and replay."""

import argparse
import asyncio
import json
from pathlib import Path


def model_options(parser):
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--mode", choices=["api", "mock"], required=True)
    parser.add_argument("--campaign", type=Path, help="shared API budget DB; authorized rounds preserve all call history")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--task-id")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="check dependencies without model requests")
    doctor.add_argument("--image")
    doctor.add_argument("--knowledge", type=Path)
    doctor.add_argument("--env-file", type=Path)
    ingest_parser = commands.add_parser("metrics-ingest")
    model_options(ingest_parser)
    source_root = ingest_parser.add_mutually_exclusive_group(required=True)
    source_root.add_argument("--root", type=Path)
    source_root.add_argument("--repo", type=Path)
    ingest_parser.add_argument("--sources", nargs="+")
    ingest_parser.add_argument("--knowledge", type=Path, required=True)
    ingest_parser.add_argument("--output", type=Path, required=True)
    run_parser = commands.add_parser("metrics-run")
    model_options(run_parser)
    run_parser.add_argument("--task", type=Path, required=True)
    run_parser.add_argument("--dataset", type=Path, required=True)
    run_parser.add_argument("--knowledge", type=Path, required=True)
    run_parser.add_argument("--image", required=True)
    run_parser.add_argument("--retrieval", choices=["none", "structured", "knowledge_off"], default="structured")
    run_parser.add_argument("--fault-injection", action="store_true")
    export_parser = commands.add_parser("metrics-export")
    export_parser.add_argument("--state", type=Path, required=True)
    export_parser.add_argument("--run", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--dataset", type=Path)
    evidence_parser = commands.add_parser("metrics-evidence")
    evidence_parser.add_argument("--state", type=Path, required=True)
    evidence_parser.add_argument("--task-id", required=True)
    evidence_parser.add_argument("--output", type=Path, required=True)
    replay_parser = commands.add_parser("metrics-replay")
    replay_parser.add_argument("--bundle", type=Path, required=True)
    replay_parser.add_argument("--expected-sha256", required=True)
    replay_parser.add_argument("--state", type=Path, required=True)
    replay_parser.add_argument("--image", required=True)
    requalify_parser = commands.add_parser("metrics-requalify")
    requalify_parser.add_argument("--source-state", type=Path, required=True)
    requalify_parser.add_argument("--run", type=Path, required=True)
    requalify_parser.add_argument("--dataset", type=Path, required=True)
    requalify_parser.add_argument("--state", type=Path, required=True)
    requalify_parser.add_argument("--knowledge", type=Path, required=True)
    requalify_parser.add_argument("--image", required=True)
    publish_parser = commands.add_parser("metrics-publish")
    publish_parser.add_argument("--state", type=Path, required=True)
    publish_parser.add_argument("--run", type=Path, required=True)
    publish_parser.add_argument("--knowledge", type=Path, required=True)
    evaluate_parser = commands.add_parser("metrics-evaluate", help="read a recorded final evaluation; never rerun test")
    evaluate_parser.add_argument("--run", type=Path, required=True)
    evaluate_parser.add_argument("--phase", choices=["final"], required=True)
    experiment_parser = commands.add_parser("metrics-experiment")
    model_options(experiment_parser)
    experiment_parser.add_argument("--config", type=Path, required=True)
    experiment_parser.add_argument("--knowledge", type=Path, required=True)
    experiment_parser.add_argument("--image", required=True)
    experiment_parser.add_argument("--output", type=Path, required=True)
    experiment_parser.add_argument("--prefix", required=True)
    focused_parser = commands.add_parser("metrics-focused-experiment")
    model_options(focused_parser)
    focused_parser.add_argument("--knowledge", type=Path, required=True)
    focused_parser.add_argument("--dataset", type=Path, required=True)
    focused_parser.add_argument("--task", type=Path, required=True)
    focused_parser.add_argument("--image", required=True)
    focused_parser.add_argument("--output", type=Path, required=True)
    focused_parser.add_argument("--prefix", required=True)
    budget = commands.add_parser("metrics-budget")
    budget.add_argument("--campaign", type=Path, required=True)
    snapshot_parser = commands.add_parser("metrics-snapshot")
    snapshot_parser.add_argument("--knowledge", type=Path, required=True)
    snapshot_parser.add_argument("--output", type=Path, required=True)
    snapshot_parser.add_argument("--sources-only", action="store_true")
    init_parser = commands.add_parser("metrics-knowledge-init", help="explicitly create Neo4j schema and namespace")
    init_parser.add_argument("--knowledge", type=Path, required=True, help="server-only Neo4j JSON configuration")
    migration_parser = commands.add_parser("metrics-knowledge-migrate", help="backup and import legacy knowledge, no model")
    migration_parser.add_argument("--source", type=Path, required=True)
    migration_parser.add_argument("--backup", type=Path, required=True, help="new backup directory, never overwrite")
    migration_parser.add_argument("--knowledge", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        from factory.metrics.doctor import diagnose
        result = diagnose(image=args.image, knowledge=args.knowledge, env_file=args.env_file)
    elif args.command in {"metrics-knowledge-init", "metrics-knowledge-migrate"}:
        from factory.metrics.knowledge_store import open_knowledge
        knowledge = open_knowledge(args.knowledge)
        try:
            if args.command == "metrics-knowledge-init":
                knowledge.initialize()
                result = {"status":"INITIALIZED", "namespace":knowledge.namespace}
            else:
                from factory.metrics.knowledge_migration import migrate
                result = migrate(args.source, args.backup, knowledge)
        finally:
            knowledge.close()
    elif args.command == "metrics-ingest":
        from factory.metrics.service import ingest_command
        result = asyncio.run(ingest_command(args))
    elif args.command == "metrics-run":
        from factory.metrics.service import run_command
        result = asyncio.run(run_command(args))
    elif args.command == "metrics-export":
        from factory.metrics.runtime import MetricsStore
        from factory.metrics.reports import export_run
        result = export_run(MetricsStore(args.state / "runtime.sqlite"), args.run, args.output, dataset_root=args.dataset)
    elif args.command == "metrics-evidence":
        from factory.metrics.runtime import MetricsStore
        from factory.metrics.reports import export_task_evidence
        result = export_task_evidence(MetricsStore(args.state / "runtime.sqlite"), args.task_id, args.output)
    elif args.command == "metrics-replay":
        from factory.metrics.replay import replay_bundle
        result = replay_bundle(args.bundle, args.expected_sha256, state=args.state, image=args.image)
    elif args.command == "metrics-requalify":
        from factory.metrics.requalification import requalify
        from factory.metrics.runtime import MetricsStore
        from factory.metrics.knowledge import KnowledgeStore
        result = requalify(MetricsStore(args.source_state / "runtime.sqlite"), args.run, args.dataset,
                          state=args.state, image=args.image, knowledge=KnowledgeStore(args.knowledge))
    elif args.command == "metrics-publish":
        from factory.metrics.knowledge import KnowledgeStore
        from factory.metrics.publication import publish_pending
        from factory.metrics.runtime import MetricsStore
        from factory.metrics.reports import bound_report
        # Re-publishing never calls a model or reruns the final test.
        store = MetricsStore(args.state / "runtime.sqlite")
        result = publish_pending(store, KnowledgeStore(args.knowledge), bound_report(store, args.run))
        # The report and prior receipts stay immutable; recovery has a separate receipt.
        if result["status"] == "PUBLISHED":
            from factory.metrics.workflow import write_json
            output = args.run / ("publication-recovery-" + result["publication_id"] + ".json")
            if not output.exists():
                write_json(output, result)
    elif args.command == "metrics-evaluate":
        from contracts.base import strict_json_loads
        report = strict_json_loads((args.run / "report.json").read_bytes())
        result = {"task_id": report["task"]["task_id"], "final": report.get("final"), "execution": "recorded_only_no_rerun"}
    elif args.command == "metrics-experiment":
        from factory.metrics.experiment import experiment_command
        result = asyncio.run(experiment_command(args))
    elif args.command == "metrics-focused-experiment":
        from factory.metrics.focused_experiment import focused
        result = asyncio.run(focused(args))
    elif args.command == "metrics-snapshot":
        from factory.metrics.knowledge import KnowledgeStore, sources_only
        from factory.metrics.workflow import write_json
        snapshot = KnowledgeStore(args.knowledge).snapshot()
        parent_id = snapshot["snapshot_id"]
        if args.sources_only:
            snapshot = sources_only(snapshot)
        write_json(args.output, snapshot)
        result = {"output": str(args.output), "snapshot_id": snapshot["snapshot_id"], "parent_snapshot_id": parent_id,
                  "sources_only": args.sources_only, "nodes": len(snapshot["nodes"])}
    else:
        from factory.metrics.budget import CallBudget
        result = CallBudget(args.campaign).summary()
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result.get("status") in {"FAILED", "BUDGET_EXHAUSTED", "NEEDS_INPUT", "PENDING_RETRY", "REVIEW_REQUIRED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
