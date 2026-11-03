"""Server-only submission check using existing CLI: mock closure, injected repair, real-code replay.

Requires a freshly initialized, empty Neo4j namespace and a new output directory.
Does not provision services, use an API configuration, or accept a campaign ledger.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.reports import bound_report
from factory.metrics.runtime import MetricsStore
from factory.runtime.artifacts import digest

RECORDED_BUNDLE_SHA = "sha256:3966a024aea5218626faffa7557f854fb48748342295e51df34ad81824d4a096"


def check(args):
    root = Path(__file__).resolve().parents[1]
    state = args.state.resolve()
    if state.exists():
        raise FileExistsError("acceptance output must be a new directory")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.prefix):
        raise ValueError("prefix must contain 1..40 letters, digits, underscores or hyphens")
    knowledge = open_knowledge(args.knowledge)
    try:
        if knowledge.snapshot()["nodes"]:
            raise ValueError("acceptance requires an empty independent knowledge namespace")
    finally:
        knowledge.close()
    state.mkdir(parents=True)
    logs = state / "logs"
    logs.mkdir()
    env = {**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + str(root)}
    # This checker cannot request real model execution, even if its caller has API settings.
    for key in ("FACTORY_METRICS_MODEL_ENV", "FACTORY_METRICS_CAMPAIGN"):
        env.pop(key, None)
    receipt = {"schema_version": "submission-acceptance/1", "real_model_requests": 0,
               "mode": "mock and historical", "commands": [], "runs": []}

    def command(name, module, *arguments):
        argv = [sys.executable, "-m", module, *map(str, arguments)]
        started = time.monotonic()
        with (logs / (name + ".stdout")).open("w") as out, (logs / (name + ".stderr")).open("w") as err:
            result = subprocess.run(argv, cwd=root, env=env, stdout=out, stderr=err)
        receipt["commands"].append({"name": name, "argv": argv, "returncode": result.returncode,
                                    "elapsed_seconds": round(time.monotonic() - started, 3)})
        (state / "acceptance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"{name} failed; original stdout/stderr retained under {logs}")
        return json.loads((logs / (name + ".stdout")).read_text().splitlines()[-1])

    snapshot = state / "extracted-knowledge.json"
    ingest = command("ingest", "factory", "metrics-ingest", "--mode", "mock", "--state", state / "workflow",
                     "--task-id", args.prefix + "-ingest", "--root", root / "materials/metrics",
                     "--knowledge", args.knowledge, "--output", snapshot)
    assert ingest["status"] == "SUCCEEDED" and all(s["status"] == "source_checked" for s in ingest["sources"])
    expected_sources = {p.name for p in (root / "materials/metrics").iterdir()
                        if p.suffix in {".md", ".txt", ".py"}}
    assert expected_sources and len(ingest["sources"]) == len(expected_sources)
    assert {source["path"] for source in ingest["sources"]} == expected_sources
    command("simulate", "factory.metrics", "simulate", "--scenario", "memory_shift", "--output", state / "dataset")
    store = MetricsStore(state / "workflow/runtime.sqlite")
    for label, inject in (("normal", False), ("injected-repair", True)):
        task_id = args.prefix + "-" + label
        arguments = ["metrics-run", "--mode", "mock", "--state", state / "workflow", "--task-id", task_id,
                     "--task", root / "examples/metrics/tasks/memory-shift.json", "--dataset", state / "dataset",
                     "--knowledge", args.knowledge, "--image", args.image]
        if inject:
            arguments.append("--fault-injection")
        result = command(label, "factory", *arguments)
        directory = Path(result["directory"])
        report = bound_report(store, directory)
        assert report["task"]["task_id"] == task_id and report["status"] == "COMPLETED"
        assert report["origin"] == ("fault_injection" if inject else "mock")
        assert report["campaign_budget"] is None and report["retrieval"]["knowledge_ids"]
        assert report["final"]["engineering_status"] == "PASSED"
        assert report["final"]["acceptance_status"] == "MEASURED_NO_ACCEPTANCE_THRESHOLD"
        if inject:
            fixed = next(c for c in report["candidates"] if c["plan"]["config"]["method_id"] == "fixed_threshold")
            assert fixed["versions"][0]["validation"]["passed"] is False
            assert len(fixed["versions"]) >= 2 and fixed["versions"][-1]["validation"]["passed"] is True
        publication = json.loads((directory / "publication.json").read_text())
        assert publication["status"] == "PUBLISHED"
        knowledge = open_knowledge(args.knowledge)
        try:
            published = knowledge.details(publication["node_ids"])
            assert {n["id"] for n in published} == set(publication["node_ids"])
            assert {"Implementation", "ValidationRun", "Experience"} <= {n["kind"] for n in published}
        finally:
            knowledge.close()
        bundle = state / (label + ".zip")
        exported = command(label + "-export", "factory", "metrics-export", "--state", state / "workflow",
                           "--run", directory, "--dataset", state / "dataset", "--output", bundle)
        command(label + "-evaluation", "factory", "metrics-evaluate", "--run", directory, "--phase", "final")
        receipt["runs"].append({"task_id": task_id, "origin": report["origin"], "directory": str(directory),
                                "selected": report["selection"]["selected"], "bundle_sha256": digest(bundle.read_bytes()),
                                "export": exported, "publication": publication, "status": report["status"],
                                "versions": {c["candidate_id"]: len(c["versions"]) for c in report["candidates"]}})
    replay = command("real-code-replay", "factory", "metrics-replay", "--bundle",
                     root / "case-example/metrics/delivery/real-memory-v1.zip", "--expected-sha256",
                     RECORDED_BUNDLE_SHA, "--state", state / "historical-replay", "--image", args.image)
    assert replay["model_calls"] == 0 and replay["effect_matches_recorded"] is True
    assert replay["original_origin"] == "llm_api" and replay["origin"] == "historical"
    receipt["historical_replay"] = replay
    command("final-knowledge", "factory", "metrics-snapshot", "--knowledge", args.knowledge,
            "--output", state / "published-knowledge.json")
    # The task ledger may contain controlled model operations, never a real API campaign.
    with sqlite3.connect((state / "workflow/runtime.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        receipt["task_count"] = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        receipt["model_modes"] = sorted({json.loads(r[0])["model_mode"] for r in db.execute("SELECT spec FROM tasks")})
    assert receipt["model_modes"] == ["mock"]
    receipt["status"] = "PASSED"
    receipt["repair_scope"] = "Controlled injection repaired with mock reference response; no new real-model repair."
    (state / "acceptance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASSED", "receipt": str(state / "acceptance.json"), "real_model_requests": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="new isolated output directory")
    parser.add_argument("--knowledge", type=Path, required=True, help="initialized empty independent Neo4j config")
    parser.add_argument("--image", required=True, help="approved full Docker image ID")
    parser.add_argument("--prefix", required=True, help="unique task prefix, max 40 characters")
    check(parser.parse_args())


if __name__ == "__main__":
    main()
