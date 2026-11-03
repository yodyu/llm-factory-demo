"""Pre-frozen paired experiment. Failed attempts stay in every success-rate denominator."""

import json
from pathlib import Path

from contracts.base import strict_json_loads
from factory.metrics.knowledge import KnowledgeStore, canonical
from factory.metrics.service import open_runtime
from factory.metrics.synthetic import generate, write_dataset
from factory.metrics.workflow import run, write_json
from factory.runtime.artifacts import digest


def summary(records, protocol):
    arms = {}
    for condition in protocol["conditions"]:
        group = [r for r in records if r["condition"] == condition]
        first_pass = repaired = eligible = candidates = 0
        success = 0
        requests = input_tokens = output_tokens = 0
        model_seconds = 0.0
        failures = {}
        for record in group:
            report = record["report"]
            candidates += 2  # Two expected candidates, even when planning itself fails.
            success += int(report["status"] == "COMPLETED" and report.get("final", {}).get("engineering_status") == "PASSED")
            for operation in report.get("model_operations", []):
                metadata = json.loads(operation["metadata"])
                requests += int(bool(operation["result_ref"]) or operation["status"] in {"SENT", "UNKNOWN"})
                input_tokens += metadata.get("input_tokens") or 0
                output_tokens += metadata.get("output_tokens") or 0
                model_seconds += metadata.get("elapsed_seconds", 0.0)
                if metadata.get("failure_code"):
                    failures[metadata["failure_code"]] = failures.get(metadata["failure_code"], 0) + 1
            for candidate in report["candidates"]:
                versions = candidate["versions"]
                first_pass += int(bool(versions) and versions[0].get("validation", {}).get("passed", False))
                repaired += max(0, len(versions) - 1)
                eligible += int(candidate.get("report", {}).get("engineering_status") == "PASSED")
        arms[condition] = {"attempted_tasks": len(group), "successful_tasks": success,
                           "task_success_rate": success / len(group) if group else None,
                           "expected_candidates": candidates, "first_pass_candidates": first_pass,
                           "first_pass_rate": first_pass / candidates if candidates else None,
                           "eligible_candidates": eligible, "eligible_rate": eligible / candidates if candidates else None,
                           "code_repairs": repaired, "sent_model_attempts": requests,
                           "input_tokens_reported": input_tokens, "output_tokens_reported": output_tokens,
                           "model_elapsed_seconds": model_seconds, "provider_failures": failures,
                           "token_notice": "missing provider usage is not estimated; no monetary cost claim"}
    return {"protocol": protocol["protocol"], "arms": arms, "attempts": [
        {"scenario": r["scenario"], "condition": r["condition"], "task_id": r["report"]["task"]["task_id"],
         "status": r["report"]["status"], "failure": r["report"].get("failure"),
         "selected": r["report"].get("selection", {}).get("selected"), "directory": r["directory"],
         "final_event_f1": r["report"].get("final", {}).get("event", {}).get("f1", {}).get("value"),
         "final_coverage": r["report"].get("final", {}).get("coverage", {}).get("value")}
        for r in records], "interpretation": protocol["interpretation"]}


async def experiment_command(args):
    protocol = strict_json_loads(args.config.read_bytes())
    if (protocol["repeats"] != 1 or protocol["conditions"] != ["none", "structured"]
            or protocol["minimum_coverage"] != 0.95):
        raise ValueError("this protocol supports one paired run per scenario")
    with KnowledgeStore(args.knowledge) as knowledge:
        snapshot = knowledge.snapshot()
    args.output.mkdir(parents=True, exist_ok=False)
    store, gateway = open_runtime(args.state, mode=args.mode, campaign=args.campaign, env_file=args.env_file)
    frozen = {"config": protocol, "snapshot_id": snapshot["snapshot_id"], "model_profile": gateway.client.profile.model_dump(mode="json"),
              "prompt_version": gateway.prompt_version,
              "image": args.image, "datasets": {}, "requests": {}}
    dataset_dirs, requests = {}, {}
    # Freeze ALL observations, labels and request parameters before any model call.
    for index, scenario in enumerate(protocol["scenarios"]):
        dataset = args.output / scenario
        bundle = generate(scenario, seed=protocol["seed_base"] + index * protocol["seed_stride"],
                          prefix_points=protocol["prefix_points"], scoring_points=protocol["scoring_points"])
        write_dataset(dataset, bundle)
        dataset_dirs[scenario] = dataset
        request = {"requirement": f"检测单主机 {bundle['manifest'].metric} 持续升高；固定阈值候选上界明确为{protocol['thresholds'][scenario]} {bundle['manifest'].unit}，比较滚动MAD，连续两点告警。短缺失按共同协议处理，报告覆盖率、误报和延迟。",
                   "anomaly_target": "upper", "expected_metric": bundle["manifest"].metric,
                   "explicit_constraints": {"threshold": protocol["thresholds"][scenario], "direction": "upper", "persistence_points": float(protocol["persistence_points"])},
                   "budgets": {"model_calls": protocol["model_calls_per_task"], "repair_rounds": protocol["repair_rounds_per_candidate"], "candidates": 2, "wall_seconds": 900}}
        requests[scenario] = request
        write_json(dataset / "request.json", request)
        frozen["datasets"][scenario] = bundle["manifest"].model_dump(mode="json")
        frozen["requests"][scenario] = digest(canonical(request).encode())
    write_json(args.output / "frozen-experiment.json", frozen)
    records, stop = [], None
    try:
        for index, scenario in enumerate(protocol["scenarios"]):
            conditions = protocol["conditions"] if index % 2 == 0 else list(reversed(protocol["conditions"]))
            for condition in conditions:
                if store.campaign and store.campaign.summary()["remaining"] < 3:
                    stop = "insufficient_remaining_campaign_slots_for_three_initial_requests"
                    break
                with KnowledgeStore(args.knowledge) as knowledge:
                    result = await run(store, gateway, state=args.state, task_input=requests[scenario], dataset_root=dataset_dirs[scenario],
                                       snapshot=snapshot, knowledge=knowledge, image=args.image,
                                       retrieval_mode=condition, task_id=args.prefix + "-" + scenario + "-" + condition)
                report = strict_json_loads((Path(result["directory"]) / "report.json").read_bytes())
                records.append({"scenario": scenario, "condition": condition, "report": report, "directory": result["directory"]})
                with (args.output / "progress.json").open("w") as stream:
                    stream.write(json.dumps(summary(records, protocol), ensure_ascii=False, indent=2) + "\n")
                if result["status"] == "BUDGET_EXHAUSTED":
                    stop = "campaign_or_task_budget_exhausted"
                    break
            if stop:
                break
    finally:
        await gateway.client.aclose()
        result = summary(records, protocol)
        result.update({"stop_reason": stop, "planned_tasks": len(protocol["scenarios"]) * 2,
                       "campaign_budget": store.campaign.summary() if store.campaign else None})
        write_json(args.output / "summary.json", result)
    return result
